"""ASGI entry point for the complaint-processing API."""

from __future__ import annotations

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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
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
