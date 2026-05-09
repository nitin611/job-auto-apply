from fastapi import APIRouter
from app.db import session_scope
from app.models import Run

router = APIRouter()


@router.get("/runs")
def list_runs(limit: int = 50):
    with session_scope() as db:
        rows = db.query(Run).order_by(Run.started_at.desc()).limit(limit).all()
        return [
            {
                "id": r.id, "kind": r.kind, "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "stats": r.stats_json,
                "error": r.error_message,
            } for r in rows
        ]
