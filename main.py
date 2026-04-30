import os
import uuid
import asyncio
import tempfile
import wave
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    FastAPI, UploadFile, File, WebSocket,
    WebSocketDisconnect, Depends, HTTPException, Body
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database.models import init_db, get_db
from database.crud import save_report, get_all_meetings, get_report, delete_meeting
from pipeline.asr import run_asr_pipeline
from pipeline.diarize import run_diarization_pipeline
from pipeline.align import run_alignment_pipeline
from graph import run_pipeline

load_dotenv()

# Read model config from .env — set by start.py, defaults to "base"
WHISPER_MODEL  = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")

# ---------------------------------------------------------------------------
# Model catalogue — shown in dashboard settings panel
# ---------------------------------------------------------------------------

AVAILABLE_MODELS = {
    "base": {
        "label":           "Base (Fastest)",
        "cpu_time":        "~2 min for a 3 min meeting",
        "gpu_time":        "~20s for a 3 min meeting",
        "accuracy":        "⭐⭐ — misses words, struggles with accents and fast speech",
        "warning":         "Noticeable errors in real meetings — use small or higher if possible",
        "ram_required_gb": 2,
    },
    "small": {
        "label":           "Small (Balanced)",
        "cpu_time":        "~6 min for a 3 min meeting",
        "gpu_time":        "~45s for a 3 min meeting",
        "accuracy":        "⭐⭐⭐ — decent accuracy, handles most accents",
        "warning":         None,
        "ram_required_gb": 4,
    },
    "medium": {
        "label":           "Medium (Good)",
        "cpu_time":        "~18 min for a 3 min meeting",
        "gpu_time":        "~2 min for a 3 min meeting",
        "accuracy":        "⭐⭐⭐⭐ — good accuracy, handles accents and crosstalk well",
        "warning":         "Too slow on CPU — recommended only on Apple Silicon or NVIDIA GPU",
        "ram_required_gb": 8,
    },
    "large-v2": {
        "label":           "Large-v2 (Best Quality)",
        "cpu_time":        "~45 min for a 3 min meeting",
        "gpu_time":        "~3 min for a 3 min meeting",
        "accuracy":        "⭐⭐⭐⭐⭐ — near-human accuracy, handles any accent or language",
        "warning":         "Only use on NVIDIA GPU with 8GB+ VRAM — CPU will be extremely slow",
        "ram_required_gb": 16,
    },
}

# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print(f"MeetMind server started. Whisper model: {WHISPER_MODEL} on {WHISPER_DEVICE}")
    yield
    print("MeetMind server stopped.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MeetMind API",
    description="Privacy-first meeting intelligence agent",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists("dashboard"):
    app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")


# ---------------------------------------------------------------------------
# Shared pipeline runner
# ---------------------------------------------------------------------------

async def process_audio_file(audio_path: str, filename: str, db: Session) -> dict:
    """
    Runs the full pipeline on an audio file and saves to database.
    Runs in a thread pool so it doesn't block the FastAPI event loop.
    """
    def _run():
        asr_result = run_asr_pipeline(audio_path, model_size=WHISPER_MODEL)
        dia_result = run_diarization_pipeline(audio_path)
        alignment  = run_alignment_pipeline(asr_result, dia_result)

        state = {
            "audio_path":           audio_path,
            "audio_filename":       filename,
            "raw_transcript":       alignment["raw_transcript"],
            "diarization_segments": dia_result["segments"],
            "duration_seconds":     alignment["duration_seconds"],
            "labelled_transcript":  alignment["labelled_transcript"],
            "speaker_profiles":     alignment["speaker_profiles"],
            "clean_transcript":     "",
            "summary":              "",
            "action_items":         [],
            "decisions":            [],
            "final_report":         None,
        }

        result = run_pipeline(state)
        report = result["final_report"]
        save_report(report, db)
        return get_report(report.meeting_id, db)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def health_check():
    return {
        "status":  "ok",
        "service": "MeetMind API",
        "version": "1.0.0",
        "model":   WHISPER_MODEL,
        "device":  WHISPER_DEVICE,
    }


@app.post("/upload")
async def upload_audio(
    file: Annotated[UploadFile, File(description="Audio file — WAV, M4A, MP3")],
    db: Session = Depends(get_db),
):
    allowed = {".wav", ".m4a", ".mp3", ".ogg", ".webm"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {', '.join(allowed)}"
        )

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    print(f"Upload received: {file.filename} ({len(content) // 1024}KB) → {tmp_path}")

    try:
        report_dict = await process_audio_file(tmp_path, file.filename or "upload", db)
        return JSONResponse(content=report_dict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.get("/meetings")
async def list_meetings(db: Session = Depends(get_db)):
    meetings = get_all_meetings(db)
    return [
        {
            "meeting_id":                m.meeting_id,
            "audio_filename":            m.audio_filename,
            "processed_at":              m.processed_at.isoformat(),
            "duration_seconds":          m.duration_seconds,
            "num_speakers":              m.num_speakers,
            "summary_preview":           m.summary_preview,
            "pipeline_duration_seconds": m.pipeline_duration_seconds,
        }
        for m in meetings
    ]


@app.get("/meetings/{meeting_id}")
async def fetch_report(meeting_id: str, db: Session = Depends(get_db)):
    result = get_report(meeting_id, db)
    if not result:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
    return result


@app.delete("/meetings/{meeting_id}")
async def remove_meeting(meeting_id: str, db: Session = Depends(get_db)):
    deleted = delete_meeting(meeting_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
    return {"deleted": True, "meeting_id": meeting_id}


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------

@app.get("/settings")
async def get_settings():
    """Returns current model config and all available options."""
    return {
        "current_model":    WHISPER_MODEL,
        "current_device":   WHISPER_DEVICE,
        "available_models": AVAILABLE_MODELS,
    }


@app.post("/settings/model")
async def update_model(model: str = Body(..., embed=True)):
    """
    Updates the Whisper model — takes effect on the next recording.
    Saves to .env so it persists across server restarts.
    """
    global WHISPER_MODEL

    if model not in AVAILABLE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model: {model}. Choose from: {list(AVAILABLE_MODELS.keys())}"
        )

    # Update .env file
    env_path = ".env"
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()

    key_found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith("WHISPER_MODEL="):
            new_lines.append(f"WHISPER_MODEL={model}\n")
            key_found = True
        else:
            new_lines.append(line)
    if not key_found:
        new_lines.append(f"WHISPER_MODEL={model}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)

    # Apply immediately without restart
    WHISPER_MODEL = model
    os.environ["WHISPER_MODEL"] = model

    print(f"Settings: Whisper model updated to {model}")

    return {
        "updated_model": model,
        "label":         AVAILABLE_MODELS[model]["label"],
        "message":       f"Model updated to {AVAILABLE_MODELS[model]['label']}. Takes effect on next recording.",
    }


# ---------------------------------------------------------------------------
# WebSocket — Chrome extension audio stream
# ---------------------------------------------------------------------------

_sessions: dict[str, list[bytes]] = {}


@app.websocket("/ws/audio")
async def websocket_audio(websocket: WebSocket, db: Session = Depends(get_db)):
    await websocket.accept()

    session_id = str(uuid.uuid4())
    _sessions[session_id] = []

    print(f"WebSocket: new session {session_id}")
    await websocket.send_json({"type": "ready", "session_id": session_id})

    try:
        while True:
            message = await websocket.receive()

            if "bytes" in message:
                _sessions[session_id].append(message["bytes"])

            elif "text" in message:
                text = message["text"].strip()

                if text == "STOP":
                    print(f"WebSocket: STOP received for session {session_id}")
                    await websocket.send_json({"type": "processing", "message": "Pipeline running..."})

                    chunks = _sessions.pop(session_id, [])
                    if not chunks:
                        await websocket.send_json({"type": "error", "message": "No audio received"})
                        break

                    wav_path = await _save_chunks_as_wav(chunks, session_id)

                    try:
                        report_dict = await process_audio_file(
                            wav_path,
                            f"extension_{session_id[:8]}.wav",
                            db
                        )
                        await websocket.send_json({
                            "type":    "report",
                            "payload": report_dict,
                        })
                        print(f"WebSocket: report sent for session {session_id}")
                    except Exception as e:
                        print(f"WebSocket: pipeline error — {e}")
                        await websocket.send_json({"type": "error", "message": str(e)})
                    finally:
                        if os.path.exists(wav_path):
                            os.unlink(wav_path)
                    break

    except WebSocketDisconnect:
        print(f"WebSocket: client disconnected — session {session_id}")
        _sessions.pop(session_id, None)


async def _save_chunks_as_wav(chunks: list[bytes], session_id: str) -> str:
    wav_path = os.path.join(tempfile.gettempdir(), f"meetmind_{session_id}.wav")
    raw_audio = b"".join(chunks)

    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(raw_audio)

    size_kb = os.path.getsize(wav_path) // 1024
    print(f"WebSocket: assembled {len(chunks)} chunks → {size_kb}KB WAV at {wav_path}")
    return wav_path