"""APScheduler foundation. Disabled by default in v1 — run-now is the primary path.

Enable by calling start_scheduler() from main.py lifespan once you trust the pipeline.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import structlog
from app.services.pipeline import run_pipeline
from app.services.export import export_day
from app.services.notify import send_digest

log = structlog.get_logger()
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    return _scheduler


async def _run_pipeline_job():
    try:
        await run_pipeline()
    except Exception:
        log.exception("scheduled_pipeline.failed")


async def _daily_digest_job():
    p = export_day()
    send_digest(attachment=p)


def start_scheduler():
    s = get_scheduler()
    s.add_job(_run_pipeline_job, CronTrigger(hour="9,15,21", minute=0), id="pipeline", replace_existing=True)
    s.add_job(_daily_digest_job, CronTrigger(hour=9, minute=0), id="digest", replace_existing=True)
    s.start()
    log.info("scheduler.started")


def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")
