"""Drishti server: ingestion + query API."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .db import SessionLocal, SpanRow, init_db, engine
from .schemas import IngestRequest, TraceSummary

API_KEY = os.environ.get("DRISHTI_API_KEY", "dev-key")

app = FastAPI(title="Drishti", version="0.1.0")

# The web UI (localhost:3000 in dev) calls this API from the browser.
# Self-hosters can widen/narrow this with DRISHTI_CORS_ORIGINS (comma-separated).
_cors_origins = os.environ.get("DRISHTI_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing x-api-key")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "drishti", "version": "0.1.0"}


@app.post("/api/v1/ingest", dependencies=[Depends(require_api_key)])
def ingest(req: IngestRequest, db: Session = Depends(get_db)) -> dict:
    rows = [
        {
            "span_id": s.span_id,
            "trace_id": s.trace_id,
            "parent_span_id": s.parent_span_id,
            "name": s.name,
            "span_type": s.span_type,
            "session_id": s.session_id,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "input": s.input,
            "output": s.output,
            "error": s.error,
            "model": s.model,
            "input_tokens": s.input_tokens,
            "output_tokens": s.output_tokens,
            "cost_usd": s.cost_usd,
            "meta": s.metadata,
        }
        for s in req.spans
    ]
    if rows:
        if engine.dialect.name == "sqlite":
            stmt = sqlite_insert(SpanRow).values(rows).on_conflict_do_nothing(index_elements=["span_id"])
            db.execute(stmt)
        else:
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = pg_insert(SpanRow).values(rows).on_conflict_do_nothing(index_elements=["span_id"])
            db.execute(stmt)
        db.commit()
    return {"accepted": len(rows)}


@app.get("/api/v1/traces", dependencies=[Depends(require_api_key)])
def list_traces(
    limit: int = Query(default=50, le=500),
    session_id: Optional[str] = None,
    db: Session = Depends(get_db),
) -> list[TraceSummary]:
    # Find the most recent trace ids first.
    trace_ids_q = (
        select(SpanRow.trace_id, func.min(SpanRow.start_time).label("t0"))
        .group_by(SpanRow.trace_id)
        .order_by(func.min(SpanRow.start_time).desc())
        .limit(limit)
    )
    if session_id:
        trace_ids_q = trace_ids_q.where(SpanRow.session_id == session_id)
    trace_ids = [row[0] for row in db.execute(trace_ids_q).all()]
    if not trace_ids:
        return []

    spans = db.execute(select(SpanRow).where(SpanRow.trace_id.in_(trace_ids))).scalars().all()

    by_trace: dict[str, list[SpanRow]] = {}
    for s in spans:
        by_trace.setdefault(s.trace_id, []).append(s)

    summaries: list[TraceSummary] = []
    for tid in trace_ids:
        group = sorted(by_trace.get(tid, []), key=lambda s: s.start_time)
        if not group:
            continue
        root = next((s for s in group if s.parent_span_id is None), group[0])
        end_times = [s.end_time for s in group if s.end_time is not None]
        duration = (max(end_times) - root.start_time) if end_times else None
        summaries.append(
            TraceSummary(
                trace_id=tid,
                name=root.name,
                session_id=root.session_id,
                start_time=root.start_time,
                duration_ms=duration,
                span_count=len(group),
                llm_call_count=sum(1 for s in group if s.span_type == "llm"),
                total_input_tokens=sum(s.input_tokens or 0 for s in group),
                total_output_tokens=sum(s.output_tokens or 0 for s in group),
                total_cost_usd=round(sum(s.cost_usd or 0.0 for s in group), 8),
                has_error=any(s.error for s in group),
            )
        )
    return summaries


@app.get("/api/v1/traces/{trace_id}", dependencies=[Depends(require_api_key)])
def get_trace(trace_id: str, db: Session = Depends(get_db)) -> dict:
    spans = (
        db.execute(select(SpanRow).where(SpanRow.trace_id == trace_id).order_by(SpanRow.start_time))
        .scalars()
        .all()
    )
    if not spans:
        raise HTTPException(status_code=404, detail="trace not found")
    return {
        "trace_id": trace_id,
        "spans": [
            {
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id,
                "name": s.name,
                "span_type": s.span_type,
                "session_id": s.session_id,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "duration_ms": (s.end_time - s.start_time) if s.end_time else None,
                "input": s.input,
                "output": s.output,
                "error": s.error,
                "model": s.model,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "cost_usd": s.cost_usd,
                "metadata": s.meta,
            }
            for s in spans
        ],
    }


@app.get("/api/v1/stats", dependencies=[Depends(require_api_key)])
def stats(db: Session = Depends(get_db)) -> dict:
    total_spans = db.execute(select(func.count(SpanRow.span_id))).scalar() or 0
    total_traces = db.execute(select(func.count(func.distinct(SpanRow.trace_id)))).scalar() or 0
    totals = db.execute(
        select(
            func.coalesce(func.sum(SpanRow.input_tokens), 0),
            func.coalesce(func.sum(SpanRow.output_tokens), 0),
            func.coalesce(func.sum(SpanRow.cost_usd), 0.0),
        )
    ).one()
    by_model = db.execute(
        select(
            SpanRow.model,
            func.count(SpanRow.span_id),
            func.coalesce(func.sum(SpanRow.input_tokens), 0),
            func.coalesce(func.sum(SpanRow.output_tokens), 0),
            func.coalesce(func.sum(SpanRow.cost_usd), 0.0),
        )
        .where(SpanRow.model.is_not(None))
        .group_by(SpanRow.model)
    ).all()
    return {
        "traces": total_traces,
        "spans": total_spans,
        "input_tokens": totals[0],
        "output_tokens": totals[1],
        "cost_usd": round(totals[2], 6),
        "by_model": [
            {
                "model": m,
                "calls": c,
                "input_tokens": it,
                "output_tokens": ot,
                "cost_usd": round(cu, 6),
            }
            for (m, c, it, ot, cu) in by_model
        ],
    }


def run() -> None:
    import uvicorn

    host = os.environ.get("DRISHTI_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("DRISHTI_SERVER_PORT", "8787"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
