"""Database layer: SQLite by default, Postgres via VEEKSHANA_DATABASE_URL."""

from __future__ import annotations

import os

from sqlalchemy import JSON, Float, Integer, String, Text, create_engine, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.environ.get("VEEKSHANA_DATABASE_URL", "sqlite:///veekshana.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class SpanRow(Base):
    __tablename__ = "spans"

    span_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(Text)
    span_type: Mapped[str] = mapped_column(String(16), default="span")
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    start_time: Mapped[float] = mapped_column(Float, index=True)  # epoch ms
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    input: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    __table_args__ = (Index("ix_spans_trace_start", "trace_id", "start_time"),)


class ScoreRow(Base):
    __tablename__ = "scores"

    score_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)  # e.g. "task_completion", "human_review"
    value: Mapped[float] = mapped_column(Float)  # 0.0–1.0
    source: Mapped[str] = mapped_column(String(16), default="llm_judge")  # "llm_judge" | "human"
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)  # judge reasoning / human note
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)  # judge model, if llm_judge
    created_at: Mapped[float] = mapped_column(Float, index=True)  # epoch ms


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """Lightweight, idempotent column additions for databases created by
    older versions (create_all never alters existing tables)."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in ("spans", "scores"):
            if table not in inspector.get_table_names():
                continue
            columns = {c["name"] for c in inspector.get_columns(table)}
            if "project_id" not in columns:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN project_id VARCHAR(64) NOT NULL DEFAULT 'default'"
                ))
