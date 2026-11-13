"""OpenTelemetry spans exported to a local JSONL file. Nothing leaves the machine."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Sequence

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

from . import paths

_lock = threading.Lock()
_configured = False


class JsonlSpanExporter(SpanExporter):
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with _lock, self.path.open("a") as f:
            for s in spans:
                f.write(json.dumps({
                    "trace_id": f"{s.context.trace_id:032x}",
                    "span_id": f"{s.context.span_id:016x}",
                    "parent_id": f"{s.parent.span_id:016x}" if s.parent else None,
                    "name": s.name,
                    "start_ns": s.start_time,
                    "duration_ms": (s.end_time - s.start_time) / 1e6,
                    "status": s.status.status_code.name,
                    "attributes": dict(s.attributes or {}),
                }, default=str) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def configure(path: Path | None = None) -> None:
    """Idempotent. Without this call spans are no-ops, which keeps tests and benchmarks quiet."""
    global _configured
    if _configured:
        return
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(JsonlSpanExporter(path or paths.traces_dir() / "spans.jsonl")))
    trace.set_tracer_provider(provider)
    _configured = True


tracer = trace.get_tracer("vice")
