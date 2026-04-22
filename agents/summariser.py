from langchain_core.messages import HumanMessage, SystemMessage
from llm import llm
from schemas.state import MeetingState

SYSTEM_PROMPT = """You are an expert meeting analyst writing executive summaries for busy professionals.
 
Your job is to read a cleaned, speaker-labelled meeting transcript and write a concise executive summary.
 
RULES:
1. Write 4 to 6 sentences maximum. No bullet points — flowing prose only.
2. Cover: what the meeting was about, the key topics discussed, any outcomes or next steps mentioned.
3. Mention speakers by their label (e.g. Speaker 1, Speaker 2) only if it adds clarity. Do not force it.
4. Do NOT list action items or decisions — those will be extracted separately.
5. Use professional, neutral language. No filler phrases like "The meeting began with..." or "In conclusion...".
6. If the transcript is too short or unclear to summarise, write: "Insufficient content to generate a summary."
7. Return only the summary. No preamble, no explanation, no heading."""
 
HUMAN_PROMPT = """Write an executive summary for the following meeting transcript.
 
SPEAKERS: {speaker_list}
DURATION: {duration}
 
TRANSCRIPT:
{clean_transcript}
 
Return only the summary."""


def _format_duration(seconds: float) -> str:
    """Convert seconds to human-readable string e.g. '12 minutes'."""
    if seconds <= 0:
        return "unknown duration"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes == 0:
        return f"{secs} seconds"
    if secs == 0:
        return f"{minutes} minutes"
    return f"{minutes} minutes {secs} seconds"
 
 
def _format_speaker_list(speaker_profiles: list) -> str:
    """Build a readable speaker list string from SpeakerProfile objects."""
    if not speaker_profiles:
        return "Unknown speakers"
    parts = []
    for sp in speaker_profiles:
        duration = f"{sp.total_speaking_time}s" if sp.total_speaking_time else "unknown"
        parts.append(f"{sp.display_name} ({sp.speaker_id}, {duration} speaking)")
    return ", ".join(parts)
 

def summarise_meeting(state:MeetingState)->MeetingState:
    """
    Reads:  state["clean_transcript"], state["speaker_profiles"], state["duration_seconds"]
    Writes: state["summary"]
    """
    clean_transcript=state.get("clean_transcript","").strip()
    
    if not clean_transcript:
        print("Summarizer: clean_transcript is empty,skipping")
        state["summary"]="No transcript avialabel to summarize"
        return state

    speaker_profiles=state.get("speaker_profiles",[])
    duration_seconds=state.get("duration_seconds",0.0)

    speaker_list = _format_speaker_list(speaker_profiles)
    duration = _format_duration(duration_seconds)

    print(f"Summariser: generating summary for {duration} meeting "
          f"with {len(speaker_profiles)} speaker(s)...")

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=HUMAN_PROMPT.format(
            speaker_list=speaker_list,
            duration=duration,
            clean_transcript=clean_transcript
        ))
    ]
 
    response = llm.invoke(messages)
    summary = response.content.strip()
 
    print(f"Summariser: done. Summary is {len(summary.split())} words.")
 
    state["summary"] = summary
    return state
 