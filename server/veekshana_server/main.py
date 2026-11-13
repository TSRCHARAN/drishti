"""Veekshana server: ingestion + query API."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import case, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .db import ScoreRow, SessionLocal, SpanRow, init_db, engine
from .otlp import parse_otlp_json, parse_otlp_protobuf
from .schemas import IngestRequest, ScoreIn, ScoreOut, SpanIn, TraceSummary

def _parse_api_keys() -> dict[str, str]:
    """Per-project API keys (open-core groundwork for multi-tenancy).

    VEEKSHANA_API_KEYS="key-a:project-a,key-b:project-b"  → key→project map
    Falls back to VEEKSHANA_API_KEY (default "dev-key") mapped to project "default",
    so single-team self-hosting needs no configuration at all.
    """
    keys: dict[str, str] = {}
    for part in os.environ.get("VEEKSHANA_API_KEYS", "").split(","):
        part = part.strip()
        if not part:
            continue
        key, _, project = part.partition(":")
        keys[key.strip()] = project.strip() or "default"
    if not keys:
        keys[os.environ.get("VEEKSHANA_API_KEY", "dev-key")] = "default"
    return keys


API_KEYS = _parse_api_keys()

app = FastAPI(title="Veekshana", version="0.1.0")

# The web UI (localhost:3000 in dev) calls this API from the browser.
# Self-hosters can widen/narrow this with VEEKSHANA_CORS_ORIGINS (comma-separated).
_cors_origins = os.environ.get("VEEKSHANA_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
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


def auth_project(x_api_key: Optional[str] = Header(default=None)) -> str:
    """Authenticate and resolve the key's project. All reads and writes are
    scoped to that project."""
    project = API_KEYS.get(x_api_key or "")
    if project is None:
        raise HTTPException(status_code=401, detail="invalid or missing x-api-key")
    return project


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "veekshana", "version": "0.1.0"}


def _insert_spans(db: Session, spans: list[SpanIn], project: str) -> int:
    rows = [
        {
            "span_id": s.span_id,
            "trace_id": s.trace_id,
            "project_id": project,
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
        for s in spans
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
    return len(rows)


@app.post("/api/v1/ingest")
def ingest(req: IngestRequest, db: Session = Depends(get_db), project: str = Depends(auth_project)) -> dict:
    return {"accepted": _insert_spans(db, req.spans, project)}


@app.post("/v1/traces")
async def otlp_traces(request: Request, db: Session = Depends(get_db), project: str = Depends(auth_project)) -> dict:
    """OTLP/HTTP trace ingest (protobuf or JSON). Point any OpenTelemetry
    exporter here: OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://<host>/v1/traces
    with OTEL_EXPORTER_OTLP_TRACES_HEADERS=x-api-key=<key>."""
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    try:
        if "json" in content_type:
            span_dicts = parse_otlp_json(body)
        else:
            span_dicts = parse_otlp_protobuf(body)
        spans = [SpanIn(**d) for d in span_dicts]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"could not parse OTLP payload: {exc}")
    _insert_spans(db, spans, project)
    return {"partialSuccess": {}}


@app.get("/api/v1/traces")
def list_traces(
    limit: int = Query(default=50, le=500),
    session_id: Optional[str] = None,
    db: Session = Depends(get_db),
    project: str = Depends(auth_project),
) -> list[TraceSummary]:
    # Find the most recent trace ids first.
    trace_ids_q = (
        select(SpanRow.trace_id, func.min(SpanRow.start_time).label("t0"))
        .where(SpanRow.project_id == project)
        .group_by(SpanRow.trace_id)
        .order_by(func.min(SpanRow.start_time).desc())
        .limit(limit)
    )
    if session_id:
        trace_ids_q = trace_ids_q.where(SpanRow.session_id == session_id)
    trace_ids = [row[0] for row in db.execute(trace_ids_q).all()]
    if not trace_ids:
        return []

    spans = (
        db.execute(
            select(SpanRow).where(SpanRow.trace_id.in_(trace_ids), SpanRow.project_id == project)
        )
        .scalars()
        .all()
    )

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


@app.get("/api/v1/traces/{trace_id}")
def get_trace(trace_id: str, db: Session = Depends(get_db), project: str = Depends(auth_project)) -> dict:
    spans = (
        db.execute(
            select(SpanRow)
            .where(SpanRow.trace_id == trace_id, SpanRow.project_id == project)
            .order_by(SpanRow.start_time)
        )
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


@app.get("/api/v1/stats")
def stats(db: Session = Depends(get_db), project: str = Depends(auth_project)) -> dict:
    in_project = SpanRow.project_id == project
    total_spans = db.execute(select(func.count(SpanRow.span_id)).where(in_project)).scalar() or 0
    total_traces = (
        db.execute(select(func.count(func.distinct(SpanRow.trace_id))).where(in_project)).scalar() or 0
    )
    totals = db.execute(
        select(
            func.coalesce(func.sum(SpanRow.input_tokens), 0),
            func.coalesce(func.sum(SpanRow.output_tokens), 0),
            func.coalesce(func.sum(SpanRow.cost_usd), 0.0),
        ).where(in_project)
    ).one()
    by_model = db.execute(
        select(
            SpanRow.model,
            func.count(SpanRow.span_id),
            func.coalesce(func.sum(SpanRow.input_tokens), 0),
            func.coalesce(func.sum(SpanRow.output_tokens), 0),
            func.coalesce(func.sum(SpanRow.cost_usd), 0.0),
        )
        .where(SpanRow.model.is_not(None), in_project)
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


@app.post("/api/v1/scores")
def create_score(score: ScoreIn, db: Session = Depends(get_db), project: str = Depends(auth_project)) -> dict:
    import time
    import uuid

    exists = db.execute(
        select(SpanRow.span_id)
        .where(SpanRow.trace_id == score.trace_id, SpanRow.project_id == project)
        .limit(1)
    ).first()
    if not exists:
        raise HTTPException(status_code=404, detail="trace not found")
    row = ScoreRow(
        score_id=uuid.uuid4().hex,
        trace_id=score.trace_id,
        project_id=project,
        name=score.name,
        value=score.value,
        source=score.source,
        comment=score.comment,
        model=score.model,
        created_at=time.time() * 1000.0,
    )
    db.add(row)
    db.commit()
    return {"score_id": row.score_id}


@app.get("/api/v1/traces/{trace_id}/scores")
def trace_scores(trace_id: str, db: Session = Depends(get_db), project: str = Depends(auth_project)) -> list[ScoreOut]:
    rows = (
        db.execute(
            select(ScoreRow)
            .where(ScoreRow.trace_id == trace_id, ScoreRow.project_id == project)
            .order_by(ScoreRow.created_at)
        )
        .scalars()
        .all()
    )
    return [
        ScoreOut(
            score_id=r.score_id, trace_id=r.trace_id, name=r.name, value=r.value,
            source=r.source, comment=r.comment, model=r.model, created_at=r.created_at,
        )
        for r in rows
    ]


@app.get("/api/v1/scores/summary")
def scores_summary(db: Session = Depends(get_db), project: str = Depends(auth_project)) -> dict:
    rows = db.execute(
        select(
            ScoreRow.name,
            func.count(ScoreRow.score_id),
            func.avg(ScoreRow.value),
            func.sum(case((ScoreRow.value < 0.5, 1), else_=0)),
        )
        .where(ScoreRow.project_id == project)
        .group_by(ScoreRow.name)
    ).all()
    scored_traces = (
        db.execute(
            select(func.count(func.distinct(ScoreRow.trace_id))).where(ScoreRow.project_id == project)
        ).scalar()
        or 0
    )
    return {
        "scored_traces": scored_traces,
        "by_name": [
            {"name": n, "count": c, "avg": round(a, 4) if a is not None else None, "low_count": int(lo or 0)}
            for (n, c, a, lo) in rows
        ],
    }


def run() -> None:
    import uvicorn

    host = os.environ.get("VEEKSHANA_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("VEEKSHANA_SERVER_PORT", "8787"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
