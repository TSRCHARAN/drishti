"""Evals v1: LLM-as-judge scoring of traces.

Reads recent unscored traces, asks a judge model "did the agent complete its
task?", and writes a 0–1 task_completion score (with reasoning) per trace.

Usage:
    drishti-eval                 # score up to 20 recent unscored traces
    drishti-eval --limit 5
    drishti-eval --mock          # no API key needed: deterministic mock judge

Judge model: $DRISHTI_EVAL_MODEL (default claude-opus-5-5) via the Anthropic SDK.
With no ANTHROPIC_API_KEY/credentials or --mock, a deterministic mock judge runs
instead, so the pipeline works out of the box.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import uuid

from sqlalchemy import select

from .db import ScoreRow, SessionLocal, SpanRow, init_db

JUDGE_MODEL = os.environ.get("DRISHTI_EVAL_MODEL", "claude-opus-5-5")
SCORE_NAME = "task_completion"

JUDGE_SYSTEM = """You are an evaluation judge for AI agent traces. You are given one trace:
the agent's task (root input), its final output, and the steps it took (LLM calls,
tool calls, errors).

Judge ONE thing: did the agent complete the task it was given?

Scoring guide:
- 1.0  task fully completed, output directly serves the request
- 0.7  mostly completed, minor gaps
- 0.4  partial: attempted but output does not really serve the request
- 0.0  failed: errored out, gave up, or output is unrelated/empty

Respond with ONLY a JSON object, no other text:
{"score": <float 0-1>, "reasoning": "<one or two sentences>"}"""


def _trace_digest(spans: list[SpanRow]) -> str:
    """Compact textual rendering of a trace for the judge."""
    spans = sorted(spans, key=lambda s: s.start_time)
    root = next((s for s in spans if s.parent_span_id is None), spans[0])
    lines = [
        f"TASK (root span '{root.name}') input: {json.dumps(root.input, default=str)[:2000]}",
        f"FINAL output: {json.dumps(root.output, default=str)[:2000]}",
        "STEPS:",
    ]
    for s in spans:
        if s.span_id == root.span_id:
            continue
        line = f"- [{s.span_type}] {s.name}"
        if s.error:
            line += f" ERROR: {s.error[:300]}"
        elif s.span_type == "tool":
            line += f" -> {json.dumps(s.output, default=str)[:300]}"
        lines.append(line)
    return "\n".join(lines)


def _mock_judge(digest: str) -> dict:
    """Deterministic mock: errors drag the score down; otherwise high-ish."""
    h = int(hashlib.sha256(digest.encode()).hexdigest(), 16)
    if "ERROR:" in digest:
        score = 0.3 + (h % 30) / 100.0  # 0.30–0.59
        reasoning = "Mock judge: a step errored; the agent recovered only partially."
    else:
        score = 0.75 + (h % 25) / 100.0  # 0.75–0.99
        reasoning = "Mock judge: all steps succeeded and the output addresses the task."
    return {"score": round(score, 2), "reasoning": reasoning}


def _llm_judge(digest: str) -> dict:
    from anthropic import Anthropic

    client = Anthropic()
    response = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=2000,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": digest}],
    )
    if response.stop_reason == "refusal":
        return {"score": 0.5, "reasoning": "Judge declined to evaluate this trace."}
    text = "".join(block.text for block in response.content if block.type == "text")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"judge returned no JSON: {text[:200]}")
    verdict = json.loads(match.group(0))
    return {
        "score": max(0.0, min(1.0, float(verdict["score"]))),
        "reasoning": str(verdict.get("reasoning", ""))[:1000],
    }


def _have_anthropic_credentials() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    # OAuth profiles on disk also work; let the SDK try and fall back on failure.
    return os.path.exists(os.path.expanduser("~/.config/anthropic"))


def run_evals(limit: int = 20, mock: bool | None = None) -> None:
    init_db()
    db = SessionLocal()
    try:
        scored = select(ScoreRow.trace_id).where(ScoreRow.name == SCORE_NAME)
        trace_ids = [
            row[0]
            for row in db.execute(
                select(SpanRow.trace_id)
                .where(SpanRow.trace_id.not_in(scored))
                .group_by(SpanRow.trace_id)
                .order_by(func_min_start())
                .limit(limit)
            ).all()
        ]
        if not trace_ids:
            print("No unscored traces found.")
            return

        use_mock = mock if mock is not None else not _have_anthropic_credentials()
        judge_name = "mock" if use_mock else JUDGE_MODEL
        print(f"Scoring {len(trace_ids)} trace(s) with judge: {judge_name}")

        for tid in trace_ids:
            spans = db.execute(select(SpanRow).where(SpanRow.trace_id == tid)).scalars().all()
            digest = _trace_digest(spans)
            try:
                verdict = _mock_judge(digest) if use_mock else _llm_judge(digest)
            except Exception as exc:
                print(f"  {tid[:8]}… judge failed: {exc}")
                continue
            db.add(
                ScoreRow(
                    score_id=uuid.uuid4().hex,
                    trace_id=tid,
                    name=SCORE_NAME,
                    value=verdict["score"],
                    source="llm_judge",
                    comment=verdict["reasoning"],
                    model=judge_name,
                    created_at=time.time() * 1000.0,
                )
            )
            db.commit()
            print(f"  {tid[:8]}… {SCORE_NAME}={verdict['score']:.2f}  {verdict['reasoning'][:80]}")
    finally:
        db.close()


def func_min_start():
    from sqlalchemy import func

    return func.min(SpanRow.start_time).desc()


def main() -> None:
    parser = argparse.ArgumentParser(description="Drishti evals: LLM-as-judge trace scoring")
    parser.add_argument("--limit", type=int, default=20, help="max unscored traces to score")
    parser.add_argument("--mock", action="store_true", help="force the deterministic mock judge")
    args = parser.parse_args()
    run_evals(limit=args.limit, mock=True if args.mock else None)


if __name__ == "__main__":
    main()
