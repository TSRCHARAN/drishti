"""Veekshana — open-source observability for AI agents.

Usage:
    import veekshana

    veekshana.init(host="http://localhost:8787", api_key="dev-key")

    @veekshana.observe()
    def my_agent(question: str) -> str:
        ...
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from .context import current_span, current_trace_id, get_session, set_session
from .decorators import observe, span, update_current_span
from .exporter import Exporter, get_exporter, set_exporter

__version__ = "0.1.0"

__all__ = [
    "init",
    "observe",
    "span",
    "update_current_span",
    "set_session",
    "get_session",
    "current_span",
    "current_trace_id",
    "flush",
]

logger = logging.getLogger("veekshana")


def init(
    host: Optional[str] = None,
    api_key: Optional[str] = None,
    instrument: bool = True,
) -> None:
    """Initialize Veekshana.

    Args:
        host: Veekshana server URL. Defaults to $VEEKSHANA_HOST or http://localhost:8787.
        api_key: Ingestion API key. Defaults to $VEEKSHANA_API_KEY or "dev-key".
        instrument: Auto-instrument installed LLM SDKs (anthropic, ...).
    """
    host = host or os.environ.get("VEEKSHANA_HOST", "http://localhost:8787")
    api_key = api_key or os.environ.get("VEEKSHANA_API_KEY", "dev-key")
    set_exporter(Exporter(host=host, api_key=api_key))

    if instrument:
        from .instrumentation import instrument_anthropic, instrument_openai

        instrument_anthropic()
        instrument_openai()


def flush() -> None:
    """Synchronously ship all queued spans (call before process exit in scripts)."""
    exporter = get_exporter()
    if exporter is not None:
        exporter.flush()
