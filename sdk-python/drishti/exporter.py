"""Background batching exporter.

Spans are queued in-process and shipped to the Drishti server in batches on a
daemon thread, so instrumentation never blocks or crashes the host app.
"""

from __future__ import annotations

import atexit
import logging
import queue
import threading
from typing import Optional

import httpx

from .models import Span

logger = logging.getLogger("drishti")

BATCH_SIZE = 50
FLUSH_INTERVAL_S = 2.0
QUEUE_MAX = 10_000


class Exporter:
    def __init__(self, host: str, api_key: str) -> None:
        self._endpoint = host.rstrip("/") + "/api/v1/ingest"
        self._api_key = api_key
        self._queue: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._client = httpx.Client(timeout=10.0)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="drishti-exporter", daemon=True)
        self._thread.start()
        atexit.register(self.shutdown)

    def submit(self, span: Span) -> None:
        try:
            self._queue.put_nowait(span.to_dict())
        except queue.Full:
            logger.warning("drishti: span queue full, dropping span %s", span.span_id)

    def _drain(self, max_items: int) -> list:
        items = []
        while len(items) < max_items:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items

    def _send(self, batch: list) -> None:
        if not batch:
            return
        try:
            resp = self._client.post(
                self._endpoint,
                json={"spans": batch},
                headers={"x-api-key": self._api_key},
            )
            if resp.status_code >= 400:
                logger.warning("drishti: ingest failed (%s): %s", resp.status_code, resp.text[:200])
        except Exception as exc:  # never break the host app
            logger.warning("drishti: ingest error: %s", exc)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(FLUSH_INTERVAL_S)
            self._send(self._drain(BATCH_SIZE))

    def flush(self) -> None:
        """Synchronously ship everything queued so far."""
        while True:
            batch = self._drain(BATCH_SIZE)
            if not batch:
                break
            self._send(batch)

    def shutdown(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self.flush()


_exporter: Optional[Exporter] = None


def get_exporter() -> Optional[Exporter]:
    return _exporter


def set_exporter(exporter: Exporter) -> None:
    global _exporter
    _exporter = exporter
