from fastapi import APIRouter, HTTPException
from app.db import session_scope
from app.models import Job

router = APIRouter()


@router.get("/jobs")
def list_jobs(status: str | None = None, limit: int = 100):
    with session_scope() as db:
        q = db.query(Job)
        if status:
            q = q.filter(Job.status == status)
        rows = q.order_by(Job.discovered_at.desc()).limit(limit).all()
        return [
            {
                "id": j.id, "title": j.title, "company": j.company,
                "source": j.source, "status": j.status, "score": j.score,
                "url": j.url, "location": j.location, "work_mode": j.work_mode,
                "posted_at": j.posted_at.isoformat() if j.posted_at else None,
                "discovered_at": j.discovered_at.isoformat(),
            }
            for j in rows
        ]


@router.post("/jobs/{job_id}/approve")
def approve(job_id: int):
    with session_scope() as db:
        j = db.query(Job).get(job_id)
        if not j:
            raise HTTPException(404)
        j.status = "approved"
    return {"ok": True}


@router.post("/jobs/{job_id}/reject")
def reject(job_id: int, reason: str = "user_rejected"):
    with session_scope() as db:
        j = db.query(Job).get(job_id)
        if not j:
            raise HTTPException(404)
        j.status = "skipped"
        j.skip_reason = reason
    return {"ok": True}
