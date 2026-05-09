import asyncio
import random
from datetime import datetime
from pathlib import Path
from app.config import ROOT


async def jitter(lo: float = 0.2, hi: float = 0.8):
    await asyncio.sleep(random.uniform(lo, hi))


async def page_jitter():
    await asyncio.sleep(random.uniform(1.0, 3.0))


def screenshot_path(job_id: int, label: str = "fail") -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    p = ROOT / "logs" / "screenshots" / f"job{job_id}-{label}-{ts}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


CAPTCHA_TEXT_HINTS = [
    "verify you are human", "i'm not a robot", "captcha", "recaptcha",
    "are you a robot", "security check", "unusual activity",
]


async def detect_blocker(page) -> str | None:
    try:
        body = (await page.locator("body").inner_text(timeout=2000)).lower()
    except Exception:
        return None
    for hint in CAPTCHA_TEXT_HINTS:
        if hint in body:
            return hint
    return None
