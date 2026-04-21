from schemas.state import MeetingState
from schemas.models import SpeakerProfile

def _overlap(asr_start:float,asr_end:float,dia_start:float,dia_end:float)-> float:
    return max(0.0,min(asr_end,dia_end)-max(asr_start,dia_start))

def assign_speakers_to_segments(asr_segments:list[dict],diarization_segments:list[dict])->list[dict]:

    
    labelled=[]
    for asr_seg in asr_segments:
        asr_start=asr_seg.get("start",0.0)
        asr_end=asr_seg.get("end",0.0)

        best_speaker="SPEAKER_UNKNOWN"
        best_overlap=0.0

        for dia_seg in diarization_segments:
            ov=_overlap(asr_start,asr_end,dia_seg["start"],dia_seg["end"])
            if ov>best_overlap:
                best_overlap=ov
                best_speaker=dia_seg["speaker"]

        labelled.append({**asr_seg,"speaker":best_speaker})

    return labelled


def _format_timestamp(seconds: float) -> str:
    """Convert float seconds to HH:MM:SS string."""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_labelled_transcript(labelled_segments:list[dict])->str:
    """
    Converts labelled segments into a readable transcript string.

    """
                
    if not labelled_segments:
        return ""

    lines=[]
    current_speaker=None
    current_start=0
    current_text_parts=[]

    for seg in labelled_segments:
        speaker=seg.get("speaker","SPEAKER_UNKNOWN")
        text=seg.get("text","").strip()
        start=seg.get("start",0.0)

        if speaker!=current_speaker:
            if current_speaker is not None and current_text_parts:
                timestamp=_format_timestamp(current_start)
                block=" ".join(current_text_parts)
                lines.append(f"[{current_speaker} | {timestamp} ]: {block}")

            current_speaker=speaker
            current_start=start
            current_text_parts=[text] if text else []


        else:
            if text:
                current_text_parts.append(text)

    
    if current_speaker is not None and current_text_parts:
        timestamp=_format_timestamp(current_start)
        block=" ".join(current_text_parts)
        lines.append(f"[{current_speaker} | {timestamp} ]: {block}")

    return "\n".join(lines)



def build_speaker_profiles(
    diarization_result: dict,
    labelled_segments: list[dict]
) -> list[SpeakerProfile]:
    """
    Build a SpeakerProfile for each unique speaker.
 
    speaker_id   — raw pyannote label e.g. "SPEAKER_00"
    display_name — human-readable e.g. "Speaker 1" 
    total_speaking_time — from diarize.py's speaker_durations
    """
    speaker_durations: dict = diarization_result.get("speaker_durations", {})
 
    seen = []
    for seg in labelled_segments:
        spk = seg.get("speaker", "SPEAKER_UNKNOWN")
        if spk not in seen:
            seen.append(spk)
 
    profiles = []
    for idx, speaker_id in enumerate(seen, start=1):
        profiles.append(
            SpeakerProfile(
                speaker_id=speaker_id,
                display_name=f"Speaker {idx}",
                total_speaking_time=speaker_durations.get(speaker_id)
            )
        )
 
    return profiles
 
def run_alignment_pipeline(
    asr_result: dict,
    diarization_result: dict
) -> dict:
    """
    Takes the outputs of run_asr_pipeline() and run_diarization_pipeline()
    and returns everything needed to populate MeetingState.
 
    """
    asr_segments: list[dict] = asr_result.get("segments", [])
    dia_segments: list[dict] = diarization_result.get("segments", [])
 
    print(f"Aligning {len(asr_segments)} ASR segments with "
          f"{len(dia_segments)} diarization turns...")
 
    labelled_segments = assign_speakers_to_segments(asr_segments, dia_segments)
    labelled_transcript = build_labelled_transcript(labelled_segments)
    speaker_profiles = build_speaker_profiles(diarization_result, labelled_segments)
 
    print(f"Alignment complete. "
          f"{len(speaker_profiles)} speaker(s) identified.")
 
    return {
        "labelled_segments": labelled_segments,
        "labelled_transcript": labelled_transcript,
        "speaker_profiles": speaker_profiles,
        "raw_transcript": asr_result.get("raw_text", ""),
        "duration_seconds": asr_result.get("duration", 0.0),
    }
 
 
def update_state_with_alignment(state: MeetingState,
                                 alignment_result: dict) -> MeetingState:
    """
    Writes alignment output into MeetingState.
    """
    state["labelled_transcript"] = alignment_result["labelled_transcript"]
    state["speaker_profiles"] = alignment_result["speaker_profiles"]
    state["raw_transcript"] = alignment_result["raw_transcript"]
    state["duration_seconds"] = alignment_result["duration_seconds"]
    return state