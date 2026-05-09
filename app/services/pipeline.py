"""End-to-end pipeline: search → score → cover letter → auto-apply."""
from __future__ import annotations
import asyncio
from datetime import datetime, date
from typing import Optional
import structlog
from sqlalchemy import func
from app.config import settings
from app.db import session_scope, SessionLocal
from app.models import Job, Application, Run, Metric
from app.schemas import ApplyResult
from app.services import events, profile as profile_svc
from app.services.dedupe import upsert_job
from app.services.filters import cheap_skip_reason
from app.sources.registry import enabled_sources
from app.apply.registry import pick_handler
from app.llm import scoring as llm_scoring
from app.llm import cover_letter as llm_cover

log = structlog.get_logger()

_run_lock = asyncio.Lock()


async def search_phase(prefs: dict) -> dict:
    sources = enabled_sources(prefs)
    events.publish("search.start", {"sources": [s.name for s in sources]})
    discovered_total = 0
    new_total = 0
    errors: list[str] = []

    for src in sources:
        try:
            postings = await src.search(prefs)
            discovered_total += len(postings)
            new_for_source = 0
            with session_scope() as db:
                for p in postings:
                    _, created = upsert_job(db, p)
                    if created:
                        new_for_source += 1
            new_total += new_for_source
            events.publish("search.source_done", {"source": src.name, "discovered": len(postings), "new": new_for_source})
        except Exception as e:
            log.exception("search.source_failed", source=src.name)
            errors.append(f"{src.name}: {e}")
            events.publish("search.source_failed", {"source": src.name, "error": str(e)})

    return {"discovered": discovered_total, "new": new_total, "errors": errors}


async def score_phase(prefs: dict, max_per_run: int = 30) -> dict:
    """Score in batches of BATCH_SIZE for speed and cost efficiency."""
    min_score = (prefs.get("scoring") or {}).get("min_score_to_qualify", 7)
    scored = 0
    qualified = 0
    skipped_cheap = 0
    skipped_score = 0
    errors = 0

    with session_scope() as db:
        rows = db.query(Job).filter(Job.status == "new").order_by(Job.discovered_at.desc()).limit(max_per_run).all()
        targets: list[int] = [j.id for j in rows]

    # Cheap filter pass first
    survivors: list[int] = []
    for job_id in targets:
        with session_scope() as db:
            job = db.query(Job).get(job_id)
            if not job:
                continue
            reason = cheap_skip_reason(job, prefs)
            if reason:
                job.status = "skipped"
                job.skip_reason = reason
                skipped_cheap += 1
                events.publish("job.skipped", {"job_id": job.id, "reason": reason})
                continue
        survivors.append(job_id)

    # Batch LLM scoring
    BATCH = llm_scoring.BATCH_SIZE
    for i in range(0, len(survivors), BATCH):
        chunk_ids = survivors[i:i + BATCH]
        with session_scope() as db:
            jobs = db.query(Job).filter(Job.id.in_(chunk_ids)).all()
            items = [{
                "id": j.id, "title": j.title, "company": j.company,
                "location": j.location, "work_mode": j.work_mode,
                "description": j.description_md or "",
            } for j in jobs]

        events.publish("score.batch_start", {"count": len(items)})
        try:
            results = await llm_scoring.score_jobs_batch(items)
        except Exception as e:
            log.exception("batch_score.failed", count=len(items))
            errors += len(items)
            events.publish("score.batch_failed", {"count": len(items), "error": str(e)})
            continue

        with session_scope() as db:
            for it in items:
                jid = it["id"]
                result = results.get(jid)
                job = db.query(Job).get(jid)
                if not job:
                    continue
                if result is None:
                    errors += 1
                    continue
                job.score = result.score
                job.score_rationale = result.rationale
                job.match_highlights = result.match_highlights
                job.red_flags = result.red_flags
                if result.score >= min_score:
                    job.status = "qualified"
                    qualified += 1
                    events.publish("job.qualified", {"job_id": job.id, "score": result.score, "title": job.title, "company": job.company})
                else:
                    job.status = "skipped"
                    job.skip_reason = f"score {result.score} < {min_score}"
                    skipped_score += 1
                    events.publish("job.skipped", {"job_id": job.id, "reason": job.skip_reason})
                scored += 1

    return {"scored": scored, "qualified": qualified, "skipped_cheap": skipped_cheap, "skipped_score": skipped_score, "errors": errors}


def _today_application_count(db, source: Optional[str] = None) -> int:
    q = db.query(func.count(Application.id)).join(Job).filter(
        func.date(Application.started_at) == date.today(),
        Application.outcome.in_(["submitted", "dry_run"]),
    )
    if source:
        q = q.filter(Job.source == source)
    return q.scalar() or 0


async def apply_phase(prefs: dict) -> dict:
    auto_threshold = (prefs.get("scoring") or {}).get("auto_apply_threshold")
    limits = prefs.get("limits") or {}
    daily_total = int(limits.get("max_applications_per_day_total", 15))
    per_source_limits = dict(limits.get("max_applications_per_source_per_day") or {})

    submitted = 0
    needs_human = 0
    failed = 0
    skipped_limit = 0

    # Pull qualified or approved jobs
    with session_scope() as db:
        rows = (db.query(Job)
                .filter(Job.status.in_(["qualified", "approved"]))
                .order_by(Job.score.desc().nullslast(), Job.discovered_at.desc())
                .all())
        candidate_ids: list[int] = []
        for j in rows:
            if j.status == "approved":
                candidate_ids.append(j.id); continue
            if auto_threshold is not None and j.score is not None and j.score >= float(auto_threshold):
                candidate_ids.append(j.id)

    for job_id in candidate_ids:
        with session_scope() as db:
            today_total = _today_application_count(db)
            if today_total >= daily_total:
                skipped_limit += 1
                events.publish("apply.daily_cap_hit", {"cap": daily_total})
                break
            job = db.query(Job).get(job_id)
            if not job:
                continue
            per_src_cap = per_source_limits.get(job.source)
            if per_src_cap is not None:
                today_src = _today_application_count(db, source=job.source)
                if today_src >= int(per_src_cap):
                    skipped_limit += 1
                    continue
            handler = await pick_handler(job)
            if handler is None:
                job.status = "needs_human"
                job.skip_reason = "no apply handler"
                needs_human += 1
                events.publish("apply.no_handler", {"job_id": job.id})
                continue
            job.status = "applying"
            db.flush()
            title = job.title; company = job.company; description = job.description_md

        # Cover letter
        try:
            cover = await llm_cover.generate_cover_letter(title, company, description or "")
        except Exception as e:
            log.warning("cover_letter.failed", job_id=job_id, error=str(e))
            cover = ""

        prefs_copy = prefs

        # Apply
        with session_scope() as db:
            job = db.query(Job).get(job_id)
            app_row = Application(job_id=job.id, started_at=datetime.utcnow())
            db.add(app_row); db.flush()
            app_id = app_row.id

        try:
            handler = await pick_handler(job)
            result: ApplyResult = await handler.apply(job, prefs_copy, cover, settings.dry_run)
        except Exception as e:
            log.exception("apply.handler_crashed", job_id=job_id)
            result = ApplyResult(outcome="failed", failure_reason=str(e)[:500])

        with session_scope() as db:
            job = db.query(Job).get(job_id)
            app_row = db.query(Application).get(app_id)
            app_row.finished_at = datetime.utcnow()
            app_row.outcome = result.outcome
            app_row.failure_reason = result.failure_reason
            app_row.screenshot_path = result.screenshot_path
            app_row.cover_letter_md = cover
            app_row.confirmation_text = result.confirmation_text

            job.cover_letter_md = cover
            if result.outcome == "submitted":
                job.status = "applied"; submitted += 1
                events.publish("apply.submitted", {"job_id": job.id, "title": job.title, "company": job.company})
            elif result.outcome == "dry_run":
                job.status = "applied"; submitted += 1
                events.publish("apply.dry_run", {"job_id": job.id, "title": job.title, "company": job.company})
            elif result.outcome == "needs_human":
                job.status = "needs_human"; needs_human += 1
                events.publish("apply.needs_human", {"job_id": job.id, "reason": result.failure_reason})
            else:
                job.status = "failed"; failed += 1
                events.publish("apply.failed", {"job_id": job.id, "reason": result.failure_reason})

    return {"submitted": submitted, "needs_human": needs_human, "failed": failed, "skipped_limit": skipped_limit}


async def run_pipeline(do_search: bool = True, do_score: bool = True, do_apply: bool = True) -> dict:
    """Run the full pipeline. Single-flight via _run_lock."""
    if _run_lock.locked():
        return {"error": "pipeline already running"}
    async with _run_lock:
        run_id: int
        with session_scope() as db:
            r = Run(kind="pipeline", started_at=datetime.utcnow(), status="running")
            db.add(r); db.flush(); run_id = r.id
        events.publish("pipeline.start", {"run_id": run_id, "dry_run": settings.dry_run})

        prefs = profile_svc.load_preferences()
        stats: dict = {}
        try:
            if do_search:
                stats["search"] = await search_phase(prefs)
            if do_score:
                stats["score"] = await score_phase(prefs)
            if do_apply:
                stats["apply"] = await apply_phase(prefs)
            with session_scope() as db:
                r = db.query(Run).get(run_id)
                r.finished_at = datetime.utcnow()
                r.status = "success"
                r.stats_json = stats
            events.publish("pipeline.done", {"run_id": run_id, "stats": stats})
        except Exception as e:
            log.exception("pipeline.failed")
            with session_scope() as db:
                r = db.query(Run).get(run_id)
                r.finished_at = datetime.utcnow()
                r.status = "error"
                r.error_message = str(e)[:1000]
                r.stats_json = stats
            events.publish("pipeline.error", {"run_id": run_id, "error": str(e)})
            raise
        return {"run_id": run_id, "stats": stats}
