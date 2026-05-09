from typing import Protocol
from app.schemas import JobPosting


class SourceClient(Protocol):
    name: str
    transport: str
    async def search(self, prefs: dict) -> list[JobPosting]: ...
