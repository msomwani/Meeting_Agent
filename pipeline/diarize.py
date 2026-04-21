import os
import numpy as np
import torch
import scipy.io.wavfile as wavfile
from pyannote.audio import Pipeline
from dotenv import load_dotenv

load_dotenv()

def load_diarization_pipeline() -> Pipeline:
    token=os.getenv("HUGGINGFACE_TOKEN")
    if not token:
        raise ValueError(
            "HUGGINGFACE_TOKEN not found in .env file"
            "Get your token from huggingface.co/settings/tokens"
        )
    
    print("Loading pyannote diarization model...")
    print("(First run downloads ~1GB of model weights takes a few minutes)")

    pipeline=Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=token
    )
    print("Diarization pipeline loaded.")
    return pipeline

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

def diarize_audio(
    audio_path:str,
    pipeline:Pipeline,
    num_of_speakers:int=None,
    min_speakers:int=None,
    max_speakers:int=None,
    )->list[dict]:

    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    
    print(f"Running diarization on: {audio_path}")

    kwargs={}
    if num_of_speakers is not None:
        kwargs["num_speakers"] = num_of_speakers
    elif min_speakers is not None or max_speakers is not None:
        if min_speakers is not None:       
            kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:      
            kwargs["max_speakers"] = max_speakers


    sample_rate, data = wavfile.read(audio_path)
    if data.ndim == 1:
        data = data[np.newaxis, :]
    else:
        data = data.T
    if data.dtype != np.float32:
        data = data.astype(np.float32) / np.iinfo(data.dtype).max
    audio_input = {"waveform": torch.from_numpy(data), "sample_rate": sample_rate}
    diarization_result = pipeline(audio_input, **kwargs)
    
    segments=[]
    annotation = diarization_result.speaker_diarization if hasattr(diarization_result, "speaker_diarization") else diarization_result
    for turn, _,speaker in annotation.itertracks(yield_label=True):
        segments.append({
            "speaker":speaker,
            "start":round(turn.start,3),
            "end":round(turn.end,3)
        })
    segments.sort(key=lambda x:x['start'])

    print(f"Diarization complete. Found {count_speakers(segments)} speakers.")
    print(f"Total segments: {len(segments)}")

    return segments

def run_diarization_pipeline(audio_path: str,
                              num_of_speakers: int = None) -> dict:
    """
    Returns:
    {
        "segments": [...],           # list of {speaker, start, end}
        "num_speakers": 2,           # how many unique speakers found
        "speaker_durations": {...}   # speaking time per speaker
    }
    """
    pipeline = load_diarization_pipeline()
    segments = diarize_audio(audio_path, pipeline, num_of_speakers=num_of_speakers)

    return {
        "segments": segments,
        "num_speakers": count_speakers(segments),
        "speaker_durations": get_speaker_durations(segments)
    }