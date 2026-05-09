from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import ROOT, settings
from app.db import session_scope
from app.models import Job, Run, Application
from sqlalchemy import func, desc
from datetime import date, datetime, timedelta
from app.services import profile as profile_svc

router = APIRouter()
templates = Jinja2Templates(directory=str(ROOT / "app" / "ui" / "templates"))


def _stats():
    with session_scope() as db:
        today_str = date.today().isoformat()
        applied_today = (db.query(func.count(Application.id))
                         .filter(func.date(Application.started_at) == today_str,
                                 Application.outcome.in_(["submitted", "dry_run"]))
                         .scalar() or 0)
        queue_waiting = (db.query(func.count(Job.id))
                         .filter(Job.status.in_(["qualified"]))
                         .scalar() or 0)
        needs_human = (db.query(func.count(Job.id))
                       .filter(Job.status == "needs_human").scalar() or 0)
        cutoff = datetime.utcnow() - timedelta(hours=24)
        failed_24h = (db.query(func.count(Application.id))
                      .filter(Application.started_at > cutoff,
                              Application.outcome == "failed").scalar() or 0)
        return {
            "applied_today": applied_today,
            "queue_waiting": queue_waiting,
            "needs_human": needs_human,
            "failed_24h": failed_24h,
            "dry_run": settings.dry_run,
        }


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    stats = _stats()
    with session_scope() as db:
        recent_apps = (db.query(Application).join(Job)
                       .order_by(Application.started_at.desc()).limit(20).all())
        recent = [{
            "ts": a.started_at.strftime("%H:%M"),
            "title": a.job.title, "company": a.job.company,
            "score": a.job.score, "outcome": a.outcome, "source": a.job.source,
            "job_id": a.job.id,
        } for a in recent_apps]
        last_runs = db.query(Run).order_by(Run.started_at.desc()).limit(5).all()
        runs = [{"id": r.id, "kind": r.kind, "status": r.status,
                 "started_at": r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "",
                 "stats": r.stats_json or {}} for r in last_runs]
    return templates.TemplateResponse(request, "dashboard.html", {
        "stats": stats, "recent": recent, "runs": runs, "page": "dashboard"
    })


@router.get("/queue", response_class=HTMLResponse)
def queue(request: Request):
    with session_scope() as db:
        rows = (db.query(Job)
                .filter(Job.status == "qualified")
                .order_by(desc(Job.score), Job.discovered_at.desc())
                .limit(50).all())
        jobs = [{
            "id": j.id, "title": j.title, "company": j.company, "source": j.source,
            "location": j.location or "", "work_mode": j.work_mode or "",
            "score": j.score, "rationale": j.score_rationale or "",
            "highlights": j.match_highlights or [], "red_flags": j.red_flags or [],
            "url": j.url, "description": (j.description_md or "")[:600],
            "posted_at": j.posted_at.strftime("%Y-%m-%d") if j.posted_at else "",
        } for j in rows]
    return templates.TemplateResponse(request, "queue.html", {"jobs": jobs, "page": "queue"})


@router.get("/jobs", response_class=HTMLResponse)
def jobs_explorer(request: Request, status: str | None = None):
    with session_scope() as db:
        q = db.query(Job)
        if status:
            q = q.filter(Job.status == status)
        rows = q.order_by(Job.discovered_at.desc()).limit(200).all()
        jobs = [{
            "id": j.id, "title": j.title, "company": j.company, "source": j.source,
            "status": j.status, "score": j.score, "location": j.location,
            "url": j.url, "discovered_at": j.discovered_at.strftime("%Y-%m-%d %H:%M"),
        } for j in rows]
    return templates.TemplateResponse(request, "jobs.html", {"jobs": jobs, "filter_status": status, "page": "jobs"})


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    prefs = profile_svc.load_preferences()
    answers = profile_svc.load_answers()
    resume_md = profile_svc.load_resume_md()
    skills_md = profile_svc.load_skills_md()
    pdf_present = profile_svc.resume_pdf_path() is not None
    return templates.TemplateResponse(request, "profile.html", {
        "prefs": prefs, "answers": answers,
        "resume_md": resume_md, "skills_md": skills_md, "pdf_present": pdf_present,
        "page": "profile",
    })


@router.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request):
    with session_scope() as db:
        rows = db.query(Run).order_by(Run.started_at.desc()).limit(50).all()
        runs = [{
            "id": r.id, "kind": r.kind, "status": r.status,
            "started_at": r.started_at.strftime("%Y-%m-%d %H:%M:%S") if r.started_at else "",
            "finished_at": r.finished_at.strftime("%H:%M:%S") if r.finished_at else "",
            "stats": r.stats_json or {}, "error": r.error_message,
        } for r in rows]
    return templates.TemplateResponse(request, "runs.html", {"runs": runs, "page": "runs"})


@router.get("/job/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: int):
    with session_scope() as db:
        j = db.query(Job).get(job_id)
        if not j:
            return HTMLResponse("Not found", status_code=404)
        apps = db.query(Application).filter_by(job_id=j.id).order_by(Application.started_at.desc()).all()
        job = {
            "id": j.id, "title": j.title, "company": j.company, "source": j.source,
            "status": j.status, "score": j.score, "rationale": j.score_rationale,
            "highlights": j.match_highlights or [], "red_flags": j.red_flags or [],
            "url": j.url, "location": j.location, "work_mode": j.work_mode,
            "description": j.description_md or "", "cover_letter": j.cover_letter_md or "",
        }
        applications = [{
            "id": a.id, "started_at": a.started_at.strftime("%Y-%m-%d %H:%M"),
            "outcome": a.outcome, "failure_reason": a.failure_reason,
            "screenshot_path": a.screenshot_path, "confirmation": a.confirmation_text,
        } for a in apps]
    return templates.TemplateResponse(request, "job_detail.html", {"job": job, "applications": applications, "page": "queue"})
