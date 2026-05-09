"""Pre-LLM cheap filters (blacklist, posted-too-old, etc.)."""
from datetime import datetime, timedelta
from app.models import Job


def cheap_skip_reason(job: Job, prefs: dict) -> str | None:
    f = prefs.get("filters") or {}
    title = (job.title or "").lower()
    desc = (job.description_md or "").lower()
    company = (job.company or "").lower()

    for kw in (f.get("blacklist_keywords") or []):
        if kw and kw.lower() in title + " " + desc:
            return f"blacklist_keyword: {kw}"

    for c in (f.get("blacklist_companies") or []):
        if c and c.lower() == company:
            return f"blacklist_company: {c}"

    must = [k.lower() for k in (f.get("must_have_keywords") or []) if k]
    if must and not any(k in (title + " " + desc) for k in must):
        return f"missing_must_have"

    age_days = f.get("exclude_if_posted_more_than_days")
    if age_days and job.posted_at:
        cutoff = datetime.utcnow() - timedelta(days=int(age_days))
        if job.posted_at < cutoff:
            return f"too_old: posted {job.posted_at.date()}"

    return None
