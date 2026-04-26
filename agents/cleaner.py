from langchain_core.messages import HumanMessage,SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from llm import llm
from schemas.state import MeetingState



SYSTEM_PROMPT = """You are a transcript cleaning specialist.
 
Your job is to clean a raw meeting transcript that was produced by an automatic speech recognition (ASR) system.
 
RULES — follow every one of these exactly:
 
1. PRESERVE speaker labels and timestamps exactly as they appear.
   Example: [SPEAKER_01 | 00:01:23] must stay exactly as [SPEAKER_01 | 00:01:23]
 
2. REMOVE filler words: um, uh, hmm, you know, like (when used as filler), so (at start of sentence), right (when repeated), okay (when repeated as filler).
 
3. REMOVE ASR hallucinations — these are repeated words or phrases that appear back-to-back with no meaning.
   Example: "Right. Right. Right. Right. Right." → "Right."
   Example: "Okay okay okay so" → "Okay, so"
 
4. FIX run-on words that ASR sometimes joins together. Use context to determine the correct split.
 
5. DO NOT paraphrase, summarise, or change the meaning of anything said.
 
6. DO NOT remove any speaker turn or timestamp line.
 
7. DO NOT add any commentary, preamble, or explanation. Return only the cleaned transcript.
 
8. If a speaker's entire turn is just filler with no real content, keep the speaker label but write: [inaudible]
"""
 
HUMAN_PROMPT = """Clean the following meeting transcript according to the rules.
 
TRANSCRIPT:
{labelled_transcript}
 
Return only the cleaned transcript. No preamble, no explanation."""
 
prompt = ChatPromptTemplate.from_messages([
    SystemMessage(content=SYSTEM_PROMPT),
    HumanMessage(content=HUMAN_PROMPT)
])

def clean_transcript(state:MeetingState)->MeetingState:
    """
    Cleans the raw transcript using the cleaner agent.
    """
    labelled_transcript=state.get("labelled_transcript","")
    if not labelled_transcript.strip():
        print("Cleaner: transcript is empty, skipping.")
        return {"clean_transcript": ""}

    print("Cleaner: cleaning transcript...")

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=HUMAN_PROMPT.format(
            labelled_transcript=labelled_transcript
        ))
    ]

    response=llm.invoke(messages)
    clean=response.content.strip()


    print(f"Cleaner: done. "
          f"Original {len(labelled_transcript)} chars → "
          f"Cleaned {len(clean)} chars.")
 
    return {"clean_transcript": clean}
    
    