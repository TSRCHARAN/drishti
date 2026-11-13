"""Toy research agent instrumented with Drishti.

Runs with NO API keys: LLM calls are mocked, but each one is recorded as a real
"llm" span with model, tokens, and cost — so you get realistic traces to explore.

Usage:
    python toy_agent.py
"""

from __future__ import annotations

import random
import time

import drishti

drishti.init()  # defaults: http://localhost:8787, api_key "dev-key"


# --- Mock LLM (stands in for a real Anthropic call; real calls are auto-captured) ---

@drishti.observe(name="llm.mock_claude", span_type="llm")
def mock_llm(prompt: str) -> str:
    time.sleep(random.uniform(0.05, 0.3))  # simulate latency
    input_tokens = len(prompt.split()) * 2
    output_tokens = random.randint(40, 400)
    drishti.update_current_span(
        model="claude-sonnet-5-5",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=(input_tokens * 2.0 + output_tokens * 10.0) / 1_000_000,
    )
    return f"[mock answer to: {prompt[:60]}...]"


# --- Tools ---

@drishti.observe(span_type="tool")
def search_web(query: str) -> list[str]:
    time.sleep(random.uniform(0.02, 0.1))
    return [f"result {i} for '{query}'" for i in range(3)]


@drishti.observe(span_type="tool")
def fetch_invoice_data(customer_id: str) -> dict:
    time.sleep(random.uniform(0.02, 0.08))
    if random.random() < 0.15:
        raise RuntimeError(f"CRM timeout fetching {customer_id}")
    return {"customer_id": customer_id, "overdue_invoices": random.randint(1, 5), "amount_inr": random.randint(10_000, 500_000)}


# --- Agent ---

@drishti.observe(name="collections_agent")
def run_agent(customer_id: str) -> str:
    plan = mock_llm(f"Plan the collections outreach for customer {customer_id}")
    try:
        invoices = fetch_invoice_data(customer_id)
    except RuntimeError:
        return mock_llm("The CRM is down. Draft an apology + retry plan.")
    context = search_web(f"payment behaviour {customer_id}")
    draft = mock_llm(f"Draft a polite payment reminder. Invoices: {invoices}. Context: {context}. Plan: {plan}")
    return draft


if __name__ == "__main__":
    drishti.set_session("demo-session-001")
    for i in range(5):
        customer = f"CUST-{1000 + i}"
        print(f"→ running agent for {customer}")
        try:
            result = run_agent(customer)
            print(f"  {result[:80]}")
        except Exception as exc:
            print(f"  agent failed: {exc}")
    drishti.flush()
    print("\nDone. Traces shipped to Drishti → GET /api/v1/traces")
