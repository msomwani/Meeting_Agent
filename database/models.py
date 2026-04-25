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


DB_PATH = os.getenv("DATABASE_PATH", "meetmind.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}, 
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class MeetingRow(Base):
    __tablename__ = "meetings"

    meeting_id      = Column(String, primary_key=True, index=True)
    audio_filename  = Column(String, nullable=False)
    processed_at    = Column(DateTime, default=datetime.now, nullable=False)
    duration_seconds = Column(Float, nullable=True)
    num_speakers    = Column(Integer, nullable=True)
    summary_preview = Column(String(300), nullable=True)  # first 300 chars of summary
    pipeline_duration_seconds = Column(Float, nullable=True)


class ReportRow(Base):
    __tablename__ = "reports"

    meeting_id          = Column(String, primary_key=True, index=True)
    summary             = Column(Text, nullable=True)
    action_items_json   = Column(Text, nullable=True)   # JSON string
    decisions_json      = Column(Text, nullable=True)   # JSON string
    speakers_json       = Column(Text, nullable=True)   # JSON string
    labelled_transcript = Column(Text, nullable=True)
    report_markdown     = Column(Text, nullable=True)


def init_db():
    """
    Creates all tables in the SQLite database if they don't exist.
    Safe to call multiple times — does nothing if tables already exist.
    Called once at FastAPI startup.
    """
    Base.metadata.create_all(bind=engine)
    print(f"Database initialised at: {DB_PATH}")


def get_db():
    """FastAPI dependency — yields a database session and closes it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()