from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class Confidence(str,Enum):
    HIGH="high"
    MEDIUM="medium"
    LOW="low"

class ActionItem(BaseModel):
    owner:str=Field(description="Who will do thsi task")
    task:str=Field(description="What needs to be done")
    deadline:Optional[str]=Field(default=None,description="When its should be completed,or None if not mentioend")
    confidence:Confidence=Field(default=Confidence.MEDIUM,description="How certain is teh LLM is that it is a real commitment")
    source_quote:Optional[str]=Field(default=None,description="The exact words from transcript this came from")

class Decision(BaseModel):
    description:str=Field(description="What was decided")
    made_by:Optional[str]=Field(default=None,description="who made or led this decision")
    timestamp_approx:Optional[str]=Field(default=None,description="approximate time in HH:MM:SS format")
    rationale:Optional[str]=Field(default=None,description="Why this decision was made,if explained")

class SpeakerProfile(BaseModel):
    speaker_id:str
    display_name:str
    total_speaking_time:Optional[float]=None

class MeetingReport(BaseModel):
    meeting_id:str
    processed_at:datetime=Field(default_factory=datetime.now)
    audio_filename:str
    duration_seconds:Optional[float]=None
    num_speakers:int
    speakers:list[SpeakerProfile]=[]
    summary:str
    action_items:list[ActionItem]=[]
    decision:list[Decision]=[]
    labelled_transcript:str
    total_tokens_used:Optional[int]=None
    pipeline_duration_seconds:Optional[float]=None


    def to_markdown(self)->str:
        lines=[
            f"Meeting Report",
            f"**Date:**{self.processed_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**File:**{self.audio_filename}",
            f"**Speakers:**{', '.join(s.display_name for s in self.speakers)}",
            "",
            "##Summary",
            self.summary,
            "",
            "##Action Items",
        ]

        if not self.action_items:
            lines.append("Not action items identified.")

        else:
            for i,item in enumerate(self.action_items,1):
                deadline=f" -due: {item.deadline}" if item.deadline else ""
                lines.append(f"{i}. **{item.owner}**: {item.task}{deadline}")
                if item.source_quote:
                    lines.append(f'   >"{item.source_quote}"')
        lines+=["","#Decisions Made"]

        if not self.decision:
            lines.append("No explicit decsion identified")
        else:
            for i,dec in enumerate(self.decision,1):
                by = f" *by {dec.made_by}*" if dec.made_by else ""
                lines.append(f"{i}. {dec.description}{by}")

        lines+=["","##Full Transcript","---",self.labelled_transcript]

        return "\n".join(lines)
               
    

    
