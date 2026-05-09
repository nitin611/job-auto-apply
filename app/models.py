from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float, ForeignKey, JSON, Index, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    job_hash = Column(String, nullable=False, unique=True, index=True)
    source = Column(String, nullable=False)
    source_job_id = Column(String, nullable=True)
    url = Column(Text, nullable=False)
    canonical_url = Column(Text, nullable=False)
    title = Column(String, nullable=False)
    company = Column(String, nullable=False)
    location = Column(String, nullable=True)
    work_mode = Column(String, nullable=True)
    ctc_min = Column(Integer, nullable=True)
    ctc_max = Column(Integer, nullable=True)
    description_md = Column(Text, nullable=True)
    posted_at = Column(DateTime, nullable=True)
    discovered_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(String, default="new", nullable=False, index=True)
    score = Column(Float, nullable=True)
    score_rationale = Column(Text, nullable=True)
    match_highlights = Column(JSON, nullable=True)
    red_flags = Column(JSON, nullable=True)
    skip_reason = Column(String, nullable=True)
    apply_handler = Column(String, nullable=True)
    cover_letter_md = Column(Text, nullable=True)
    raw_payload = Column(JSON, nullable=True)

    applications = relationship("Application", back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_jobs_source_discovered", "source", "discovered_at"),
        Index("ix_jobs_score", "score"),
    )


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    outcome = Column(String, nullable=True)  # submitted | failed | needs_human | dry_run
    failure_reason = Column(Text, nullable=True)
    screenshot_path = Column(String, nullable=True)
    cover_letter_md = Column(Text, nullable=True)
    screening_answers_json = Column(JSON, nullable=True)
    confirmation_text = Column(Text, nullable=True)

    job = relationship("Job", back_populates="applications")


class Run(Base):
    __tablename__ = "runs"
    id = Column(Integer, primary_key=True)
    kind = Column(String, nullable=False)  # search | score | apply | pipeline | export | digest
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, default="running", nullable=False)
    stats_json = Column(JSON, nullable=True)
    log_path = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)


class ProfileState(Base):
    __tablename__ = "profile_state"
    id = Column(Integer, primary_key=True)
    content_hash = Column(String, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    system_prompt = Column(Text, nullable=True)


class Metric(Base):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True)
    day = Column(String, nullable=False, index=True)  # YYYY-MM-DD
    key = Column(String, nullable=False)
    value = Column(Float, nullable=False, default=0)
    __table_args__ = (UniqueConstraint("day", "key", name="uq_metrics_day_key"),)
