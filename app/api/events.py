from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from app.services.events import subscribe

router = APIRouter()


@router.get("/events")
async def stream():
    async def gen():
        async for chunk in subscribe():
            yield chunk.removeprefix("data: ").rstrip("\n")
    return EventSourceResponse(gen())
