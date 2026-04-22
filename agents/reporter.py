import uuid
from datetime import datetime
from schemas.state import MeetingState
from schemas.models import (
    MeetingReport,
    ActionItem,
    Decision,
    SpeakerProfile,
)


def assemble_report(state: MeetingState) -> MeetingState:
    """
    Reads:  summary, action_items, decisions, speaker_profiles,
            labelled_transcript, duration_seconds, audio_filename
    Writes: state["final_report"]
 
    No LLM call — this is pure data assembly and Pydantic validation.
    """
    print("Reporter: assembling final report...")

    speaker_profiles: list[SpeakerProfile] = state.get("speaker_profiles", [])

    validated_speakers = []
    for sp in speaker_profiles:
        if isinstance(sp, SpeakerProfile):
            validated_speakers.append(sp)
        elif isinstance(sp, dict):
            try:
                validated_speakers.append(SpeakerProfile(**sp))
            except Exception as e:
                print(f"Reporter: skipping invalid speaker profile — {e}")
 
    action_items_raw: list[dict] = state.get("action_items", [])

    validated_actions = []
    for item in action_items_raw:
        if isinstance(item, ActionItem):
            validated_actions.append(item)
        elif isinstance(item, dict):
            try:
                validated_actions.append(ActionItem(**item))
            except Exception as e:
                print(f"Reporter: skipping invalid action item — {e}")

    decisions_raw: list[dict] = state.get("decisions", [])
    validated_decisions = []
    for dec in decisions_raw:
        if isinstance(dec, Decision):
            validated_decisions.append(dec)
        elif isinstance(dec, dict):
            try:
                validated_decisions.append(Decision(**dec))
            except Exception as e:
                print(f"Reporter: skipping invalid decision — {e}")

    meeting_id = str(uuid.uuid4())
 
    report = MeetingReport(
        meeting_id=meeting_id,
        processed_at=datetime.now(),
        audio_filename=state.get("audio_filename", "unknown"),
        duration_seconds=state.get("duration_seconds", 0.0),
        num_speakers=len(validated_speakers),
        speakers=validated_speakers,
        summary=state.get("summary", "No summary available."),
        action_items=validated_actions,
        decision=validated_decisions,
        labelled_transcript=state.get("clean_transcript", "") or state.get("labelled_transcript", ""),
        total_tokens_used=None,       
        pipeline_duration_seconds=None,
    )
 
    print(f"Reporter: done.")
    print(f"  meeting_id      : {report.meeting_id}")
    print(f"  speakers        : {report.num_speakers}")
    print(f"  action items    : {len(report.action_items)}")
    print(f"  decisions       : {len(report.decision)}")
    print(f"  summary length  : {len(report.summary.split())} words")
 
    state["final_report"] = report
    return state