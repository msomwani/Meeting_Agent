import whisperx
import os
from dotenv import load_dotenv

load_dotenv()

def load_whisper_model(model_size:str="base", device:str="cpu"):
    """
    Loads the WhisperX model into memory.
    
    model_size options:
        "base"    — fastest, less accurate
        "small"   — good balance for testing
        "large-v2" — most accurate
    
    device options:
        "cpu"  — works everywhere, slower
        "cuda" — needs an NVIDIA GPU, much faster
        "mps"  — Apple Silicon Mac, faster than cpu
    """
    print(f"Loading Whisper Model: {model_size} on {device}")
    model=whisperx.load_model(
        model_size,
        device=device,
        compute_type="float32"
    )
    print("Whisper model loaded.")
    return model

def audio_transcribe(audio_path:str,model)-> dict :
    """
Transcribe an audio file and return segments with timestamps.

Returns a dict with:
    - segments: list of {text, start, end}
    - language: detected language code e.g. "en"
"""
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    
    print(f"Transcribing audio: {audio_path}")

    audio=whisperx.load_audio(audio_path)
    result=model.transcribe(audio,batch_size=4)

    print(f"Transciption completed. Detected language :{result['language']}")
    print(f"Number of segments {len(result['segments'])} ")

    return result


def align_whisper_output(result: dict, model, audio_path: str) -> dict:
    """
    Improve timestamp precision using WhisperX alignment.

    """
    
    print("Aligning timestamps to word level...")
    
    # Load the alignment model for the detected language
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
    
    print("Alignment complete.")
    return result_aligned


def get_transcript_text(segments: list) -> str:
    """
    Flatten all segments into a single plain text string.
    
    """
    return " ".join(segment["text"].strip() for segment in segments)


def run_asr_pipeline(audio_path: str, model_size: str = "base") -> dict:
    """
    Full ASR pipeline 
    
    """
    
    import torch
    if torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"
    
    print(f"Using device: {device}")
    
    # Load model
    model = load_whisper_model(model_size=model_size, device=device)
    
    # Transcribe
    result = audio_transcribe(audio_path, model)
    
    # Align to word level
    # Note: alignment model always runs on cpu — MPS not supported
    # for the alignment model specifically
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
    
    # Calculate duration from last segment
    duration = 0.0
    if result_aligned["segments"]:
        duration = result_aligned["segments"][-1]["end"]
    
    return {
        "segments": result_aligned["segments"],
        "language": result["language"],
        "raw_text": get_transcript_text(result_aligned["segments"]),
        "duration": duration
    }