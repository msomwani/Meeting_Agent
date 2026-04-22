import json
from langchain_core.messages import HumanMessage, SystemMessage
from llm import llm
from schemas.state import MeetingState
from schemas.models import Decision

SYSTEM_PROMPT = """You are an expert meeting analyst specialising in identifying decisions.
 
A decision is a conclusion that was reached, agreed upon, or confirmed during the meeting.
It is different from an action item — a decision is a choice made, not a task assigned.
 
Examples of decisions:
- "We will use PostgreSQL instead of MongoDB"
- "The launch date is confirmed for Q4"
- "The dashboard redesign is the top priority for this sprint"
 
RULES:
1. Only extract real decisions — not suggestions under discussion, open questions, or maybes.
2. Each decision must have a clear description of what was decided.
3. Set made_by to the speaker label or name if it is clear who made or led the decision. Otherwise null.
4. Set timestamp_approx to the nearest timestamp from the transcript in HH:MM:SS format if available. Otherwise null.
5. Set rationale to the reason given for the decision, if one was stated. Otherwise null.
6. If there are no decisions, return an empty list: []
7. Return ONLY a valid JSON array. No preamble, no explanation, no markdown code fences.
 
Each item must follow this exact structure:
{
  "description": "string — what was decided",
  "made_by": "string or null — who made or led the decision",
  "timestamp_approx": "string or null — HH:MM:SS format",
  "rationale": "string or null — why this decision was made"
}"""
 
HUMAN_PROMPT = """Extract all decisions made in the following meeting transcript.
 
TRANSCRIPT:
{clean_transcript}
 
Return only a valid JSON array of decisions. If none exist, return []."""

def extract_decisions(state:MeetingState)->MeetingState:
    """
    Reads:  state["clean_transcript"]
    Writes: state["decisions"]
     """

    clean_transcript = state.get("clean_transcript", "").strip()

    if not clean_transcript:
        print("Decisions: clean_transcript is empty, skipping.")
        state["decisions"] = []
        return state
 
    print("Decisions: extracting decisions...")
 
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=HUMAN_PROMPT.format(
            clean_transcript=clean_transcript
        ))
    ]
 
    response = llm.invoke(messages)
    raw = response.content.strip()

     # Strip markdown fences if LLM adds them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
 
    # Parse and validate with Pydantic
    try:
        items_raw = json.loads(raw)
        validated = []
        for item in items_raw:
            try:
                validated.append(Decision(**item).model_dump())
            except Exception as e:
                print(f"Decisions: skipping invalid item — {e}")
 
        print(f"Decisions: done. Found {len(validated)} decision(s).")
        state["decisions"] = validated
 
    except json.JSONDecodeError as e:
        print(f"Decisions: JSON parse error — {e}")
        print(f"Decisions: raw response was: {raw[:300]}")
        state["decisions"] = []
 
    return state