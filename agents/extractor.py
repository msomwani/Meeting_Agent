import json
from langchain_core.messages import HumanMessage, SystemMessage
from llm import llm
from schemas.state import MeetingState
from schemas.models import ActionItem

SYSTEM_PROMPT = """You are an expert meeting analyst specialising in extracting action items.
 
An action item is a clear commitment made by a named person (or group) to complete a specific task, 
sometimes with a deadline.
 
RULES:
1. Only extract real commitments — not suggestions, hypotheticals, or general discussion.
2. Each action item must have an owner (who) and a task (what).
3. Include a deadline only if one was explicitly mentioned. Otherwise set it to null.
4. Set confidence to "high" if the commitment was explicit and clear.
   Set to "medium" if it was implied but reasonably certain.
   Set to "low" if you are guessing.
5. Include a short source_quote — the exact words from the transcript that led to this action item.
6. If there are no action items, return an empty list: []
7. Return ONLY a valid JSON array. No preamble, no explanation, no markdown code fences.
 
Each item must follow this exact structure:
{
  "owner": "string — who will do it, use speaker label if name unknown e.g. SPEAKER_01",
  "task": "string — what needs to be done",
  "deadline": "string or null — when it should be done",
  "confidence": "high" | "medium" | "low",
  "source_quote": "string or null — exact words from transcript"
}"""
 
HUMAN_PROMPT = """Extract all action items from the following meeting transcript.
 
TRANSCRIPT:
{clean_transcript}
 
Return only a valid JSON array of action items. If none exist, return []."""
 

def extract_action_items(state:MeetingState)->MeetingState:
    """
    Reads:  state["clean_transcript"]
    Writes: state["action_items"]
    """
    clean_transcript=state.get("clean_transcript","").strip()

    if not clean_transcript:
        print("Extractor: clean_transcript is empty, skipping.")
        return {"action_items": []}
    
    print("Extractor: Extracting action items...")


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
                validated.append(ActionItem(**item).model_dump())
            except Exception as e:
                print(f"Extractor: skipping invalid item — {e}")
 
        print(f"Extractor: done. Found {len(validated)} action item(s).")

    except json.JSONDecodeError as e:
        print(f"Extractor: JSON parse error — {e}")
        print(f"Extractor: raw response was: {raw[:300]}")
        return {"action_items": []}
 
    return {"action_items": validated}