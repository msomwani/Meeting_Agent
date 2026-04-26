import os
import uuid
import asyncio
import tempfile
import wave
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    FastAPI, UploadFile, File, WebSocket,
    WebSocketDisconnect, Depends, HTTPException
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise database on startup."""
    init_db()
    print("MeetMind server started.")
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
    allow_origins=["*"],        # tightened in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists("dashboard"):
    app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")


async def process_audio_file(audio_path: str, filename: str, db: Session) -> dict:
    """
    Runs the full pipeline on an audio file and saves to database.
    """
    def _run():
        # Audio layer
        asr_result = run_asr_pipeline(audio_path, model_size="base")
        dia_result = run_diarization_pipeline(audio_path)
        alignment  = run_alignment_pipeline(asr_result, dia_result)

        # Build initial state
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

        # LangGraph agent pipeline
        result = run_pipeline(state)
        report = result["final_report"]

        # Save to database
        save_report(report, db)

        return get_report(report.meeting_id, db)

    # Run blocking pipeline in thread pool
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run)


@app.get("/")
async def health_check():
    return {"status": "ok", "service": "MeetMind API", "version": "1.0.0"}


@app.post("/upload")
async def upload_audio(
    file: Annotated[UploadFile, File(description="Audio file — WAV, M4A, MP3")],
    db: Session = Depends(get_db),
):
    """
    Upload an audio file and run the full pipeline.
    Returns the complete meeting report as JSON.
    """
    # Validate file type
    allowed = {".wav", ".m4a", ".mp3", ".ogg", ".webm"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {', '.join(allowed)}"
        )

    # Save upload to a temp file
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
    """
    Returns all meetings ordered by most recent first.
    Used by the dashboard history page.
    """
    meetings = get_all_meetings(db)
    return [
        {
            "meeting_id":       m.meeting_id,
            "audio_filename":   m.audio_filename,
            "processed_at":     m.processed_at.isoformat(),
            "duration_seconds": m.duration_seconds,
            "num_speakers":     m.num_speakers,
            "summary_preview":  m.summary_preview,
            "pipeline_duration_seconds": m.pipeline_duration_seconds,
        }
        for m in meetings
    ]


@app.get("/meetings/{meeting_id}")
async def fetch_report(meeting_id: str, db: Session = Depends(get_db)):
    """
    Returns the full report for a specific meeting.
    Used by the dashboard report view page.
    """
    result = get_report(meeting_id, db)
    if not result:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
    return result


@app.delete("/meetings/{meeting_id}")
async def remove_meeting(meeting_id: str, db: Session = Depends(get_db)):
    """Deletes a meeting and its report from the database."""
    deleted = delete_meeting(meeting_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
    return {"deleted": True, "meeting_id": meeting_id}


# ---------------------------------------------------------------------------
# WebSocket — Chrome extension audio stream
# ---------------------------------------------------------------------------

# Active recording sessions: session_id → list of raw audio bytes chunks
_sessions: dict[str, list[bytes]] = {}


@app.websocket("/ws/audio")
async def websocket_audio(websocket: WebSocket, db: Session = Depends(get_db)):
    """
    WebSocket endpoint for the Chrome extension.

    Protocol:
        1. Extension connects → server sends {"type": "ready", "session_id": "..."}
        2. Extension sends raw audio chunks (bytes) continuously
        3. Extension sends text message "STOP" when recording ends
        4. Server assembles chunks → WAV file → runs pipeline → sends report JSON back
        5. Connection closes

    The offscreen.js in the Chrome extension streams audio chunks here
    and sends "STOP" when the user clicks Stop in the popup.
    """
    await websocket.accept()

    session_id = str(uuid.uuid4())
    _sessions[session_id] = []

    print(f"WebSocket: new session {session_id}")
    await websocket.send_json({"type": "ready", "session_id": session_id})

    try:
        while True:
            message = await websocket.receive()

            # Binary audio chunk
            if "bytes" in message:
                _sessions[session_id].append(message["bytes"])

            # Text control message
            elif "text" in message:
                text = message["text"].strip()

                if text == "STOP":
                    print(f"WebSocket: STOP received for session {session_id}")
                    await websocket.send_json({"type": "processing", "message": "Pipeline running..."})

                    chunks = _sessions.pop(session_id, [])
                    if not chunks:
                        await websocket.send_json({"type": "error", "message": "No audio received"})
                        break

                    # Assemble chunks into a WAV file
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
    """
    Assembles raw PCM audio chunks from the Chrome extension into a WAV file.

    Chrome's tabCapture API delivers raw PCM audio at 48000Hz, mono, 16-bit.
    These parameters match what the extension's offscreen.js will configure.
    """
    wav_path = os.path.join(tempfile.gettempdir(), f"meetmind_{session_id}.wav")

    raw_audio = b"".join(chunks)

    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)       # mono
        wf.setsampwidth(2)       # 16-bit = 2 bytes
        wf.setframerate(48000)   # Chrome tabCapture default sample rate
        wf.writeframes(raw_audio)

    size_kb = os.path.getsize(wav_path) // 1024
    print(f"WebSocket: assembled {len(chunks)} chunks → {size_kb}KB WAV at {wav_path}")
    return wav_path