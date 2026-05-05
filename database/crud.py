"""
database/crud.py
"""

import json
from sqlalchemy.orm import Session
from schemas.models import MeetingReport
from database.models import MeetingRow, ReportRow


def save_report(report: MeetingReport, db: Session, audio_path: str = None) -> MeetingRow:
    """Persists a completed MeetingReport to SQLite."""

    action_items_json = json.dumps(
        [item.model_dump() for item in report.action_items], default=str
    )
    decisions_json = json.dumps(
        [dec.model_dump() for dec in report.decision], default=str
    )
    speakers_json = json.dumps(
        [sp.model_dump() for sp in report.speakers], default=str
    )

    meeting_row = MeetingRow(
        meeting_id=report.meeting_id,
        audio_filename=report.audio_filename,
        audio_path=audio_path,                  # saved permanently on disk
        processed_at=report.processed_at,
        duration_seconds=report.duration_seconds,
        num_speakers=report.num_speakers,
        summary_preview=report.summary[:300] if report.summary else None,
        pipeline_duration_seconds=report.pipeline_duration_seconds,
    )

    report_row = ReportRow(
        meeting_id=report.meeting_id,
        summary=report.summary,
        action_items_json=action_items_json,
        decisions_json=decisions_json,
        speakers_json=speakers_json,
        labelled_transcript=report.labelled_transcript,
        report_markdown=report.to_markdown(),
    )

    db.add(meeting_row)
    db.add(report_row)
    db.commit()
    db.refresh(meeting_row)

    print(f"Database: saved meeting {report.meeting_id} — {report.audio_filename}")
    return meeting_row


def get_all_meetings(db: Session) -> list[MeetingRow]:
    return db.query(MeetingRow).order_by(MeetingRow.processed_at.desc()).all()


def get_report(meeting_id: str, db: Session) -> dict | None:
    meeting = db.query(MeetingRow).filter(MeetingRow.meeting_id == meeting_id).first()
    if not meeting:
        return None

    report = db.query(ReportRow).filter(ReportRow.meeting_id == meeting_id).first()
    if not report:
        return None

    import os
    return {
        "meeting_id":                meeting.meeting_id,
        "audio_filename":            meeting.audio_filename,
        "processed_at":              meeting.processed_at.isoformat(),
        "duration_seconds":          meeting.duration_seconds,
        "num_speakers":              meeting.num_speakers,
        "pipeline_duration_seconds": meeting.pipeline_duration_seconds,
        "has_audio":                 bool(meeting.audio_path and os.path.exists(meeting.audio_path)),
        "summary":                   report.summary,
        "action_items":              json.loads(report.action_items_json or "[]"),
        "decisions":                 json.loads(report.decisions_json or "[]"),
        "speakers":                  json.loads(report.speakers_json or "[]"),
        "labelled_transcript":       report.labelled_transcript,
        "report_markdown":           report.report_markdown,
    }


def delete_meeting(meeting_id: str, db: Session) -> bool:
    meeting = db.query(MeetingRow).filter(MeetingRow.meeting_id == meeting_id).first()
    if not meeting:
        return False

    report = db.query(ReportRow).filter(ReportRow.meeting_id == meeting_id).first()
    if report:
        db.delete(report)

    db.delete(meeting)
    db.commit()

    print(f"Database: deleted meeting {meeting_id}")
    return True