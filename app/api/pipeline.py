import asyncio
from fastapi import APIRouter, BackgroundTasks
from app.services.pipeline import run_pipeline
from app.llm.client import health_check

router = APIRouter()

_current_task: asyncio.Task | None = None


@router.post("/pipeline/run")
async def run_now(background: BackgroundTasks):
    """Kick off the full pipeline as a background task. Returns immediately."""
    global _current_task
    if _current_task and not _current_task.done():
        return {"status": "already_running"}
    _current_task = asyncio.create_task(run_pipeline())
    return {"status": "started"}


@router.post("/pipeline/search")
async def search_only():
    global _current_task
    if _current_task and not _current_task.done():
        return {"status": "already_running"}
    _current_task = asyncio.create_task(run_pipeline(do_search=True, do_score=False, do_apply=False))
    return {"status": "started"}


@router.post("/pipeline/score")
async def score_only():
    global _current_task
    if _current_task and not _current_task.done():
        return {"status": "already_running"}
    _current_task = asyncio.create_task(run_pipeline(do_search=False, do_score=True, do_apply=False))
    return {"status": "started"}


@router.post("/pipeline/apply")
async def apply_only():
    global _current_task
    if _current_task and not _current_task.done():
        return {"status": "already_running"}
    _current_task = asyncio.create_task(run_pipeline(do_search=False, do_score=False, do_apply=True))
    return {"status": "started"}


@router.get("/pipeline/status")
async def pipeline_status():
    running = _current_task is not None and not _current_task.done()
    return {"running": running}


@router.get("/pipeline/health")
async def health():
    ok, msg = await health_check()
    return {"claude_ok": ok, "claude_message": msg}


@router.post("/pipeline/export")
async def export_today():
    from app.services.export import export_day
    p = export_day()
    return {"path": str(p)}


@router.post("/pipeline/digest")
async def send_digest_now():
    from app.services.notify import send_digest
    from app.services.export import export_day
    p = export_day()
    sent = send_digest(attachment=p)
    return {"sent": sent, "attachment": str(p)}
