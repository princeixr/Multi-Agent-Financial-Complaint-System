"""ASGI entry point for the complaint-processing API."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.db.session import init_db
from app.observability.logging import setup_logging
from app.observability.tracing import setup_tracing
from app.ui import router as ui_router

logger = logging.getLogger(__name__)


def _log_langsmith_hint() -> None:
    """LangSmith is opt-in via env; OTEL in this repo does not send data to LangSmith."""
    tracing_on = os.getenv("LANGCHAIN_TRACING_V2", "").lower() in ("1", "true", "yes")
    tracing_on = tracing_on or os.getenv("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes")
    has_key = bool(os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY"))
    project = os.getenv("LANGCHAIN_PROJECT") or os.getenv("LANGSMITH_PROJECT") or "(default project)"

    if tracing_on and has_key:
        logger.info("LangSmith tracing appears enabled (project=%s)", project)
    elif tracing_on and not has_key:
        logger.warning(
            "Tracing flag is on but LANGCHAIN_API_KEY / LANGSMITH_API_KEY is missing; "
            "LangSmith will not receive runs"
        )
    else:
        logger.info(
            "LangSmith off: set LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY "
            "(see .env.example) to send LangGraph/LangChain traces to LangSmith"
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    _log_langsmith_hint()
    setup_tracing()
    init_db()
    yield


app = FastAPI(
    title="Complaint classification agent",
    description="LangGraph pipeline for consumer complaint intake, classification, risk, and resolution.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (CSS, JS)
static_dir = Path(__file__).resolve().parent / "app" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# API routes
app.include_router(api_router)

# UI routes (HTML views)
app.include_router(ui_router)
