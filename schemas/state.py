from typing import TypedDict,Optional
from schemas.models import MeetingReport

class MeetingState(TypedDict):
  audio_path: str
  audio_filename:str
  raw_transcript: str        
  diarization_segments: list  
  duration_seconds:float
  labelled_transcript: str   
  speaker_profiles:list
  clean_transcript: str       
  summary: str                
  action_items: list[dict]   
  decisions: list[dict]       
  final_report: Optional[MeetingReport]
  