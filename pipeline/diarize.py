import os
from dotenv import load_dotenv

load_dotenv()


# ── Shared utilities ──────────────────────────────────────────────────────────

def count_speakers(segments: list[dict]) -> int:
    """Count unique speakers in the diarization output."""
    return len(set(seg["speaker"] for seg in segments))


def get_speaker_durations(segments: list[dict]) -> dict[str, float]:
    """
    Calculate total speaking time per speaker in seconds.
    Used to populate SpeakerProfile in the final report.
    """
    durations = {}
    for seg in segments:
        speaker = seg["speaker"]
        duration = seg["end"] - seg["start"]
        durations[speaker] = durations.get(speaker, 0.0) + duration

    return {k: round(v, 1) for k, v in durations.items()}


# ── Local helpers (pyannote) ──────────────────────────────────────────────────

def load_diarization_pipeline():
    from pyannote.audio import Pipeline

    token = os.getenv("HUGGINGFACE_TOKEN")
    if not token:
        raise ValueError(
            "HUGGINGFACE_TOKEN not found in .env file. "
            "Get your token from huggingface.co/settings/tokens"
        )

    print("Loading pyannote diarization model...")
    print("(First run downloads ~1GB of model weights — takes a few minutes)")

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=token
    )
    print("Diarization pipeline loaded.")
    return pipeline


def _to_wav(audio_path: str) -> tuple[str, bool]:
    """Return (wav_path, was_converted). Converts non-WAV via ffmpeg."""
    import subprocess
    import tempfile
    if audio_path.lower().endswith(".wav"):
        return audio_path, False
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", tmp.name],
        capture_output=True, check=True
    )
    return tmp.name, True


def diarize_audio(
    audio_path: str,
    pipeline,
    num_of_speakers: int = None,
    min_speakers: int = None,
    max_speakers: int = None,
) -> list[dict]:
    import numpy as np
    import torch
    import scipy.io.wavfile as wavfile

    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    print(f"Running diarization on: {audio_path}")

    kwargs = {}
    if num_of_speakers is not None:
        kwargs["num_speakers"] = num_of_speakers
    elif min_speakers is not None or max_speakers is not None:
        if min_speakers is not None:
            kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            kwargs["max_speakers"] = max_speakers

    wav_path, converted = _to_wav(audio_path)
    try:
        sample_rate, data = wavfile.read(wav_path)
        if data.ndim == 1:
            data = data[np.newaxis, :]
        else:
            data = data.T
        if data.dtype != np.float32:
            data = data.astype(np.float32) / np.iinfo(data.dtype).max
        audio_input = {"waveform": torch.from_numpy(data), "sample_rate": sample_rate}
        diarization_result = pipeline(audio_input, **kwargs)
    finally:
        if converted:
            os.unlink(wav_path)

    segments = []
    annotation = (
        diarization_result.speaker_diarization
        if hasattr(diarization_result, "speaker_diarization")
        else diarization_result
    )
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        segments.append({
            "speaker": speaker,
            "start": round(turn.start, 3),
            "end": round(turn.end, 3),
        })
    segments.sort(key=lambda x: x["start"])

    print(f"Diarization complete. Found {count_speakers(segments)} speakers.")
    print(f"Total segments: {len(segments)}")

    return segments


def _run_diarization_local(audio_path: str, num_speakers: int = None) -> dict:
    pipeline = load_diarization_pipeline()
    segments = diarize_audio(audio_path, pipeline, num_of_speakers=num_speakers)

    return {
        "segments": segments,
        "num_speakers": count_speakers(segments),
        "speaker_durations": get_speaker_durations(segments),
    }


# ── Cloud helper (AssemblyAI) ─────────────────────────────────────────────────

def _run_diarization_cloud(audio_path: str, num_speakers: int = None) -> dict:
    import assemblyai as aai

    api_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not api_key:
        raise ValueError("ASSEMBLYAI_API_KEY not set in environment")

    aai.settings.api_key = api_key

    config_kwargs = {"speaker_labels": True}
    if num_speakers:
        config_kwargs["speakers_expected"] = num_speakers
    config = aai.TranscriptionConfig(**config_kwargs)

    print(f"Running AssemblyAI diarization on: {audio_path}")
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(audio_path, config=config)

    if transcript.error:
        raise RuntimeError(f"AssemblyAI transcription failed: {transcript.error}")

    utterances = transcript.utterances or []
    segments = [
        {
            "speaker": f"SPEAKER_{utterance.speaker}",
            "start": round(utterance.start / 1000.0, 3),
            "end": round(utterance.end / 1000.0, 3),
        }
        for utterance in utterances
    ]
    segments.sort(key=lambda x: x["start"])

    num_speakers_found = count_speakers(segments)
    print(f"AssemblyAI diarization complete. Found {num_speakers_found} speakers.")

    return {
        "segments": segments,
        "num_speakers": num_speakers_found,
        "speaker_durations": get_speaker_durations(segments),
    }


# ── Public entry point ────────────────────────────────────────────────────────

def run_diarization_pipeline(audio_path: str, num_of_speakers: int = None) -> dict:
    """
    Returns:
    {
        "segments": [...],           # list of {speaker, start, end}
        "num_speakers": 2,
        "speaker_durations": {...}
    }
    Branches on USE_LOCAL_MODELS env var.
    """
    use_local = os.getenv("USE_LOCAL_MODELS", "true").lower() == "true"

    if use_local:
        return _run_diarization_local(audio_path, num_speakers=num_of_speakers)
    else:
        return _run_diarization_cloud(audio_path, num_speakers=num_of_speakers)
