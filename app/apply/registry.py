from app.apply.greenhouse import GreenhouseApply
from app.apply.lever import LeverApply

HANDLERS = [GreenhouseApply(), LeverApply()]


async def pick_handler(job):
    for h in HANDLERS:
        if await h.can_handle(job):
            return h
    return None
