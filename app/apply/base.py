from typing import Protocol
from app.models import Job
from app.schemas import ApplyResult


class ApplyHandler(Protocol):
    source: str
    async def can_handle(self, job: Job) -> bool: ...
    async def apply(self, job: Job, profile: dict, cover_letter: str, dry_run: bool) -> ApplyResult: ...
