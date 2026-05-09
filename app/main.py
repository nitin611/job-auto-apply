from contextlib import asynccontextmanager
import logging
import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.config import settings, ROOT
from app.db import init_db
from app.api import jobs as api_jobs
from app.api import profile as api_profile
from app.api import runs as api_runs
from app.api import events as api_events
from app.api import pipeline as api_pipeline
from app.ui import routes as ui_routes


def _configure_logging():
    logging.basicConfig(level=settings.log_level)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    init_db()
    yield


app = FastAPI(title="Auto Job Apply", lifespan=lifespan)

static_dir = ROOT / "app" / "ui" / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(ui_routes.router)
app.include_router(api_jobs.router, prefix="/api")
app.include_router(api_profile.router, prefix="/api")
app.include_router(api_runs.router, prefix="/api")
app.include_router(api_events.router, prefix="/api")
app.include_router(api_pipeline.router, prefix="/api")
