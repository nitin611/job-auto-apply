from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class JobPosting(BaseModel):
    """Normalized output from any source client."""
    source: str
    source_job_id: Optional[str] = None
    url: str
    canonical_url: str
    title: str
    company: str
    location: Optional[str] = None
    work_mode: Optional[str] = None
    ctc_min: Optional[int] = None
    ctc_max: Optional[int] = None
    description_md: Optional[str] = None
    posted_at: Optional[datetime] = None
    apply_handler: Optional[str] = None
    raw_payload: dict = Field(default_factory=dict)


class ScoreResult(BaseModel):
    score: float
    rationale: str
    red_flags: list[str] = Field(default_factory=list)
    match_highlights: list[str] = Field(default_factory=list)


class ApplyResult(BaseModel):
    outcome: str  # submitted | failed | needs_human | dry_run
    failure_reason: Optional[str] = None
    screenshot_path: Optional[str] = None
    confirmation_text: Optional[str] = None
    screening_answers: Optional[list[dict]] = None
