"""In-memory pub/sub for SSE."""
import asyncio
import json
from collections import deque
from datetime import datetime
from typing import AsyncIterator

_subscribers: list[asyncio.Queue] = []
_recent: deque[dict] = deque(maxlen=200)


def publish(event_type: str, data: dict) -> None:
    payload = {"type": event_type, "ts": datetime.utcnow().isoformat(), **data}
    _recent.append(payload)
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


async def subscribe() -> AsyncIterator[str]:
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _subscribers.append(q)
    try:
        for evt in list(_recent)[-20:]:
            yield f"data: {json.dumps(evt)}\n\n"
        while True:
            evt = await q.get()
            yield f"data: {json.dumps(evt)}\n\n"
    finally:
        if q in _subscribers:
            _subscribers.remove(q)
