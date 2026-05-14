import os
from dotenv import load_dotenv

load_dotenv()


# ── Local helpers (WhisperX) ──────────────────────────────────────────────────

def load_whisper_model(model_size: str = "base", device: str = "cpu"):
    """
    Loads the WhisperX model into memory.

    model_size options:
        "base"     — fastest, less accurate
        "small"    — good balance for testing
        "medium"   — good accuracy
        "large-v2" — most accurate

    device options:
        "cpu"  — works everywhere, including Apple Silicon
        "cuda" — needs an NVIDIA GPU, much faster
        Note: MPS is NOT supported by ctranslate2 — always use cpu on Apple Silicon
    """
    import whisperx
    print(f"Loading Whisper Model: {model_size} on {device}")
    model = whisperx.load_model(
        model_size,
        device=device,
        compute_type="float32"
    )
    print("Whisper model loaded.")
    return model


def audio_transcribe(audio_path: str, model) -> dict:
    """
    Transcribe an audio file and return segments with timestamps.

    Returns a dict with:
        - segments: list of {text, start, end}
        - language: detected language code e.g. "en"
    """
    import whisperx
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    print(f"Transcribing audio: {audio_path}")

    audio = whisperx.load_audio(audio_path)
    result = model.transcribe(audio, batch_size=4)

    print(f"Transcription completed. Detected language: {result['language']}")
    print(f"Number of segments: {len(result['segments'])}")

    return result


def get_transcript_text(segments: list) -> str:
    """Flatten all segments into a single plain text string."""
    return " ".join(segment["text"].strip() for segment in segments)


def _run_asr_local(audio_path: str, model_size: str, preloaded_model) -> dict:
    import torch
    import whisperx

    if torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"

    print(f"Using device: {device}")

    model = preloaded_model if preloaded_model is not None else load_whisper_model(
        model_size=model_size, device=device
    )

    result = audio_transcribe(audio_path, model)

    align_model, metadata = whisperx.load_align_model(
        language_code=result["language"],
        device="cpu"
    )
    audio = whisperx.load_audio(audio_path)
    result_aligned = whisperx.align(
        result["segments"],
        align_model,
        metadata,
        audio,
        device="cpu",
        return_char_alignments=False
    )

    duration = 0.0
    if result_aligned["segments"]:
        duration = result_aligned["segments"][-1]["end"]

    return {
        "segments": result_aligned["segments"],
        "language": result["language"],
        "raw_text": get_transcript_text(result_aligned["segments"]),
        "duration": duration,
    }


# ── Cloud helper (Groq Whisper API) ──────────────────────────────────────────

def _run_asr_cloud(audio_path: str) -> dict:
    from groq import Groq

    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set in environment")

    print(f"Transcribing via Groq Whisper API: {audio_path}")

    client = Groq(api_key=api_key)
    with open(audio_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            file=f,
            model="whisper-large-v3",
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    raw_segments = transcription.segments or []
    segments = [
        {"text": seg.text, "start": seg.start, "end": seg.end}
        for seg in raw_segments
    ]

    duration = segments[-1]["end"] if segments else 0.0

    print(f"Groq transcription complete. Language: {transcription.language}, "
          f"Segments: {len(segments)}")

    return {
        "segments": segments,
        "language": transcription.language or "en",
        "raw_text": get_transcript_text(segments),
        "duration": duration,
    }


# ── Public entry point ────────────────────────────────────────────────────────

def run_asr_pipeline(
    audio_path: str,
    model_size: str = "base",
    preloaded_model=None
) -> dict:
    """
    Full ASR pipeline. Branches on USE_LOCAL_MODELS env var.

    Args:
        audio_path:       Path to audio file
        model_size:       Whisper model size — V1 only (ignored in cloud mode)
        preloaded_model:  Already-loaded WhisperX model — V1 only
    """
    use_local = os.getenv("USE_LOCAL_MODELS", "true").lower() == "true"

    if use_local:
        return _run_asr_local(audio_path, model_size, preloaded_model)
    else:
        return _run_asr_cloud(audio_path)
