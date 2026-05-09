"""Gmail SMTP digest sender."""
import smtplib
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
import structlog
from app.config import settings
from app.db import session_scope
from app.models import Application, Job

log = structlog.get_logger()


def _summarize(day: date) -> str:
    from datetime import timedelta
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    with session_scope() as db:
        applied = db.query(Application).filter(Application.started_at >= start, Application.started_at < end,
                                                Application.outcome.in_(["submitted", "dry_run"])).count()
        failed = db.query(Application).filter(Application.started_at >= start, Application.started_at < end,
                                               Application.outcome == "failed").count()
        needs_human = db.query(Application).filter(Application.started_at >= start, Application.started_at < end,
                                                    Application.outcome == "needs_human").count()
        new_jobs = db.query(Job).filter(Job.discovered_at >= start, Job.discovered_at < end).count()
    return (f"Auto Job Apply — {day.isoformat()}\n\n"
            f"Discovered: {new_jobs}\nApplied: {applied}\nFailed: {failed}\nNeeds human review: {needs_human}\n")


def send_digest(day: date | None = None, attachment: Path | None = None) -> bool:
    if not settings.gmail_address or not settings.gmail_app_password:
        log.info("notify.skip", reason="gmail not configured")
        return False
    day = day or date.today()
    msg = EmailMessage()
    msg["Subject"] = f"AutoApply digest — {day.isoformat()}"
    msg["From"] = settings.gmail_address
    msg["To"] = settings.gmail_address
    msg.set_content(_summarize(day))

    if attachment and attachment.exists():
        msg.add_attachment(attachment.read_bytes(),
                           maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           filename=attachment.name)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(settings.gmail_address, settings.gmail_app_password)
            s.send_message(msg)
        log.info("notify.sent", day=str(day))
        return True
    except Exception as e:
        log.exception("notify.failed", error=str(e))
        return False
