"""
database/models.py

SQLAlchemy table definitions for MeetMind.

Two tables:
    meetings — one row per processed meeting (metadata only)
    reports  — one row per meeting (full content: summary, JSON, transcript)
"""

import os
from datetime import datetime
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Float,
    Integer,
    DateTime,
    Text,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Engine + Session
# ---------------------------------------------------------------------------

DB_PATH = os.getenv("DATABASE_PATH", "meetmind.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Table: meetings
# ---------------------------------------------------------------------------

class MeetingRow(Base):
    __tablename__ = "meetings"

    meeting_id                = Column(String, primary_key=True, index=True)
    audio_filename            = Column(String, nullable=False)
    audio_path                = Column(String, nullable=True)   # path to saved WAV on disk
    processed_at              = Column(DateTime, default=datetime.now, nullable=False)
    duration_seconds          = Column(Float, nullable=True)
    num_speakers              = Column(Integer, nullable=True)
    summary_preview           = Column(String(300), nullable=True)
    pipeline_duration_seconds = Column(Float, nullable=True)


# ---------------------------------------------------------------------------
# Table: reports
# ---------------------------------------------------------------------------

class ReportRow(Base):
    __tablename__ = "reports"

    meeting_id          = Column(String, primary_key=True, index=True)
    summary             = Column(Text, nullable=True)
    action_items_json   = Column(Text, nullable=True)
    decisions_json      = Column(Text, nullable=True)
    speakers_json       = Column(Text, nullable=True)
    labelled_transcript = Column(Text, nullable=True)
    report_markdown     = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_db():
    """
    Creates all tables if they don't exist.
    Also adds audio_path column if upgrading from an older schema.
    """
    Base.metadata.create_all(bind=engine)

    # Safe migration — add audio_path column if it doesn't exist yet
    # (handles existing databases that were created before this column was added)
    from sqlalchemy import text, inspect
    with engine.connect() as conn:
        inspector = inspect(engine)
        columns = [c["name"] for c in inspector.get_columns("meetings")]
        if "audio_path" not in columns:
            conn.execute(text("ALTER TABLE meetings ADD COLUMN audio_path TEXT"))
            conn.commit()
            print("Database: added audio_path column to meetings table.")

    print(f"Database initialised at: {DB_PATH}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()