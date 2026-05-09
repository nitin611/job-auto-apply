import hashlib
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Job
from app.schemas import JobPosting

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                    "gh_src", "trk", "src", "ref", "fbclid", "gclid"}


def canonicalize_url(url: str) -> str:
    try:
        p = urlparse(url)
        q = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in _TRACKING_PARAMS]
        return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", urlencode(q), ""))
    except Exception:
        return url


def job_hash(source: str, canonical_url: str, company: str, title: str) -> str:
    raw = f"{source}|{canonical_url}|{company.lower().strip()}|{title.lower().strip()}"
    return hashlib.sha1(raw.encode()).hexdigest()


def upsert_job(db: Session, posting: JobPosting) -> tuple[Job, bool]:
    """Returns (Job, created)."""
    canon = canonicalize_url(posting.url)
    h = job_hash(posting.source, canon, posting.company, posting.title)
    existing = db.query(Job).filter_by(job_hash=h).one_or_none()
    if existing:
        return existing, False
    job = Job(
        job_hash=h,
        source=posting.source,
        source_job_id=posting.source_job_id,
        url=posting.url,
        canonical_url=canon,
        title=posting.title,
        company=posting.company,
        location=posting.location,
        work_mode=posting.work_mode,
        ctc_min=posting.ctc_min,
        ctc_max=posting.ctc_max,
        description_md=posting.description_md,
        posted_at=posting.posted_at,
        discovered_at=datetime.utcnow(),
        status="new",
        apply_handler=posting.apply_handler,
        raw_payload=posting.raw_payload,
    )
    db.add(job)
    db.flush()
    return job, True
