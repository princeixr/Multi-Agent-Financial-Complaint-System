"""Database engine, session factory, and pgvector extension bootstrap."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base

logger = logging.getLogger(__name__)

# ── Connection URL ───────────────────────────────────────────────────────────
# Default points to a local Postgres with pgvector installed.
# Override via the DATABASE_URL environment variable.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/complaints",
)

_connect_args: dict = {}
if DATABASE_URL.startswith("postgresql"):
    _connect_args["connect_timeout"] = int(os.getenv("PG_CONNECT_TIMEOUT", "5"))

engine = create_engine(
    DATABASE_URL,
    echo=bool(os.getenv("SQL_ECHO", "")),
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    """Enable the pgvector extension and create all tables (idempotent).

    Must be called once at application startup (or during migrations).
    """
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
        logger.info("pgvector extension ensured")

    # Create tables first — must exist before migration block runs
    Base.metadata.create_all(bind=engine)
    logger.info("All database tables created / verified")

    # When the demo repo evolves, new columns may be added to existing
    # tables. Since this project doesn't ship with Alembic migrations,
    # we do safe "add column if missing" for the known schema upgrades.
    with engine.connect() as conn:
        columns_to_ensure: list[tuple[str, str]] = [
            ("external_schema_json", "TEXT"),
            ("operational_mapping_json", "TEXT"),
            ("evidence_trace_json", "TEXT"),
            ("severity_class", "VARCHAR(40)"),
            ("team_assignment", "VARCHAR(120)"),
            ("sla_class", "VARCHAR(40)"),
            ("root_cause_hypothesis_json", "TEXT"),
            ("compliance_flags_json", "TEXT"),
            ("review_notes", "TEXT"),
            ("routed_to", "VARCHAR(120)"),
            ("classification_audit_json", "TEXT"),
        ]

        classification_columns: list[tuple[str, str]] = [
            ("review_recommended", "BOOLEAN DEFAULT FALSE"),
            ("reason_codes_json", "TEXT"),
            ("keywords_json", "TEXT"),
        ]

        for table_name, columns in (
            ("complaint_cases", complaint_case_columns),
            ("classifications", classification_columns),
        ):
            existing = conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = :table_name
                    AND column_name = ANY(:cols)
                    """
                ),
                {"table_name": table_name, "cols": [c[0] for c in columns]},
            ).fetchall()
            existing_cols = {r[0] for r in existing}

            for col_name, col_type in columns:
                if col_name in existing_cols:
                    continue
                logger.info("Adding missing column to %s: %s", table_name, col_name)
                conn.execute(
                    text(
                        f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"
                    )
                )
        conn.commit()


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Yield a transactional DB session and handle cleanup."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
