import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pyannote")

import os
import uuid
import asyncio
import tempfile
import threading
import wave
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    FastAPI, UploadFile, File, WebSocket,
    WebSocketDisconnect, Depends, HTTPException, Body
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database.models import init_db, get_db, SessionLocal
from database.crud import save_report, get_all_meetings, get_report, delete_meeting
from pipeline.asr import run_asr_pipeline, load_whisper_model
from pipeline.diarize import run_diarization_pipeline
from pipeline.align import run_alignment_pipeline
from graph import run_pipeline

load_dotenv()

WHISPER_MODEL  = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")

# Pre-loaded model instance — avoids 10s delay on first recording
_whisper_model = None

# Directory where meeting audio is permanently saved
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Model catalogue
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
# Startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _whisper_model

    init_db()

    # Pre-load Whisper model at startup — first recording is instant
    print(f"Loading Whisper model '{WHISPER_MODEL}' on {WHISPER_DEVICE}...")
    try:
        _whisper_model = load_whisper_model(
            model_size=WHISPER_MODEL,
            device=WHISPER_DEVICE
        )
        print(f"Whisper model ready.")
    except Exception as e:
        print(f"Warning: could not pre-load Whisper model — {e}")
        print("Model will be loaded on first recording instead.")
        _whisper_model = None

    print(f"MeetMind server started. Whisper model: {WHISPER_MODEL} on {WHISPER_DEVICE}")
    yield
    print("MeetMind server stopped.")


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
# Pipeline runner
# ---------------------------------------------------------------------------

async def process_audio_file(audio_path: str, filename: str, db: Session) -> dict:
    """
    Runs the full pipeline on an audio file and saves to database.
    Uses the pre-loaded model if available — falls back to loading fresh.
    """
    def _run():
        # Use pre-loaded model if it matches current setting
        # If user switched models via dashboard, load the new one
        model = _whisper_model
        asr_result = run_asr_pipeline(
            audio_path,
            model_size=WHISPER_MODEL,
            preloaded_model=model
        )
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
        save_report(report, db, audio_path=audio_path)
        return get_report(report.meeting_id, db)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def health_check():
    return {
        "status":        "ok",
        "service":       "MeetMind API",
        "version":       "1.0.0",
        "model":         WHISPER_MODEL,
        "device":        WHISPER_DEVICE,
        "model_loaded":  _whisper_model is not None,
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

    recording_id   = str(uuid.uuid4())
    permanent_path = os.path.join(RECORDINGS_DIR, f"{recording_id}{ext}")

    content = await file.read()
    with open(permanent_path, "wb") as f:
        f.write(content)

    print(f"Upload saved: {file.filename} ({len(content) // 1024}KB) → {permanent_path}")

    try:
        report_dict = await process_audio_file(
            permanent_path, file.filename or "upload", db
        )
        return JSONResponse(content=report_dict)
    except Exception as e:
        if os.path.exists(permanent_path):
            os.unlink(permanent_path)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")


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
            "has_audio":                 bool(m.audio_path and os.path.exists(m.audio_path)),
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
    from database.models import MeetingRow
    meeting = db.query(MeetingRow).filter(
        MeetingRow.meeting_id == meeting_id
    ).first()

    if meeting and meeting.audio_path and os.path.exists(meeting.audio_path):
        os.unlink(meeting.audio_path)
        print(f"Deleted audio: {meeting.audio_path}")

    deleted = delete_meeting(meeting_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
    return {"deleted": True, "meeting_id": meeting_id}


@app.get("/meetings/{meeting_id}/audio")
async def download_audio(meeting_id: str, db: Session = Depends(get_db)):
    from database.models import MeetingRow
    meeting = db.query(MeetingRow).filter(
        MeetingRow.meeting_id == meeting_id
    ).first()

    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if not meeting.audio_path or not os.path.exists(meeting.audio_path):
        raise HTTPException(
            status_code=404,
            detail="Audio file not available for this meeting"
        )

    download_name = meeting.audio_filename or f"meeting_{meeting_id[:8]}.wav"
    return FileResponse(
        path=meeting.audio_path,
        media_type="audio/wav",
        filename=download_name,
    )


# ---------------------------------------------------------------------------
# Session status — lets the extension poll for pipeline success/failure
# ---------------------------------------------------------------------------

@app.get("/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    raw = _session_status.get(session_id, "processing")
    if raw.startswith("error:"):
        return {"status": "error", "message": raw[6:]}
    return {"status": raw}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.get("/settings")
async def get_settings():
    return {
        "current_model":    WHISPER_MODEL,
        "current_device":   WHISPER_DEVICE,
        "available_models": AVAILABLE_MODELS,
    }


@app.post("/settings/model")
async def update_model(model: str = Body(..., embed=True)):
    global WHISPER_MODEL, _whisper_model

    if model not in AVAILABLE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model: {model}. Choose from: {list(AVAILABLE_MODELS.keys())}"
        )

    env_path = ".env"
    with _env_lock:
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

    # Update in memory
    WHISPER_MODEL  = model
    os.environ["WHISPER_MODEL"] = model

    # Clear pre-loaded model — new model loads on next recording
    _whisper_model = None

    print(f"Settings: Whisper model updated to {model} — will load on next recording")

    return {
        "updated_model": model,
        "label":         AVAILABLE_MODELS[model]["label"],
        "message":       f"Model updated to {AVAILABLE_MODELS[model]['label']}. Takes effect on next recording.",
    }


# ---------------------------------------------------------------------------
# WebSocket — Chrome extension audio stream
# ---------------------------------------------------------------------------

_sessions: dict[str, list[bytes]] = {}
_session_status: dict[str, str] = {}   # session_id → "processing" | "done" | "error:<msg>"
_env_lock = threading.Lock()


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

                    chunks = _sessions.pop(session_id, [])
                    if not chunks:
                        await websocket.send_json({"type": "error", "message": "No audio received"})
                        break

                    filename       = f"extension_{session_id[:8]}.wav"
                    permanent_path = os.path.join(RECORDINGS_DIR, filename)
                    await _save_chunks_as_wav(chunks, permanent_path)

                    # Acknowledge immediately — pipeline runs in background
                    await websocket.send_json({
                        "type":       "accepted",
                        "session_id": session_id,
                        "message":    "Recording received — processing in background",
                    })

                    asyncio.create_task(
                        _process_in_background(permanent_path, filename, session_id)
                    )
                    break

    except WebSocketDisconnect:
        print(f"WebSocket: client disconnected — session {session_id}")
        _sessions.pop(session_id, None)


async def _process_in_background(audio_path: str, filename: str, session_id: str):
    print(f"Background: starting pipeline for {session_id[:8]}…")
    _session_status[session_id] = "processing"
    db = SessionLocal()
    try:
        await process_audio_file(audio_path, filename, db)
        _session_status[session_id] = "done"
        print(f"Background: pipeline complete for {session_id[:8]}")
    except Exception as e:
        _session_status[session_id] = f"error:{e}"
        print(f"Background: pipeline error for {session_id[:8]} — {e}")
    finally:
        db.close()


async def _save_chunks_as_wav(chunks: list[bytes], output_path: str):
    """
    Assembles MediaRecorder webm/opus chunks into a WAV file via ffmpeg.
    Resamples to 16kHz mono — optimal for Whisper.
    """
    raw_audio = b"".join(chunks)
    webm_path = output_path.replace(".wav", ".webm")

    with open(webm_path, "wb") as f:
        f.write(raw_audio)

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", webm_path,
        "-ar", "16000", "-ac", "1", "-f", "wav", output_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if os.path.exists(webm_path):
        os.unlink(webm_path)

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {stderr.decode()}")

    size_kb = os.path.getsize(output_path) // 1024
    print(f"WebSocket: {len(chunks)} chunks → converted → {size_kb}KB WAV → {output_path}")