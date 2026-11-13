"""Thin wrapper around the TypeSafe SDK.

Failures raise JudgeError. A failed call is never turned into an answer here; callers
decide what an unavailable judgment means.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .config import Config
from .tracing import tracer


class JudgeError(Exception):
    pass


@dataclass
class JudgeResult:
    answers: dict[str, dict]  # question id -> plain answer dict
    model: str
    input_tokens: int
    latency_ms: float
    cached: bool = False


class Judge(Protocol):
    async def ask(self, state: Any, questions: Mapping[str, Any], *, timeout_s: float | None = None) -> JudgeResult: ...


def _payload(model: str, state: Any, questions: Mapping[str, Any]) -> dict:
    return {
        "model": model,
        "state": state,
        "questions": {k: (q.model_dump() if hasattr(q, "model_dump") else q) for k, q in questions.items()},
    }


class TypeSafeJudge:
    def __init__(self, cfg: Config, cache_dir: Path | None = None, payload_log: Path | None = None):
        import httpx2
        from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

        self.cfg = cfg
        self.cache_dir = cache_dir
        self.payload_log = payload_log
        self.read_cache = True  # False = always call the API but still record answers
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        # Long keep-alive: ambient events are sparse, and a cold TLS handshake alone can
        # exceed the gate's latency budget.
        self._http = httpx2.AsyncClient(
            http2=cfg.http2,
            limits=httpx2.Limits(max_connections=32, max_keepalive_connections=32, keepalive_expiry=cfg.keepalive_s),
        )
        self._client = AsyncTypeSafeClient(
            model=cfg.model,
            http_client=self._http,
            timeout=cfg.request_timeout_s,
            # Interactive path: one quick retry at most. Latency matters more than persistence.
            retry=RetryPolicy(max_retries=1, backoff_initial=0.05, backoff_max=0.2, timeout=cfg.request_timeout_s),
        )

    async def warm(self) -> None:
        """Open the connection ahead of the first event. Free: listing models bills no tokens."""
        try:
            await self._client.models.list()
        except Exception as e:  # noqa: BLE001
            raise JudgeError(f"warm-up failed: {e}") from e

    async def ask(self, state, questions, *, timeout_s=None) -> JudgeResult:
        payload = _payload(self.cfg.model, state, questions)
        key = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        if self.cache_dir and self.read_cache and (hit := self.cache_dir / f"{key}.json").exists():
            d = json.loads(hit.read_text())
            return JudgeResult(d["answers"], d["model"], d["input_tokens"], d["latency_ms"], cached=True)

        with tracer.start_as_current_span("jev.system_one") as span:
            span.set_attribute("jev.questions", len(questions))
            t0 = time.perf_counter()
            try:
                resp = await self._client.system_one(state=state, questions=questions, timeout=timeout_s)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                span.record_exception(e)
                raise JudgeError(f"{type(e).__name__}: {e}") from e
            latency_ms = (time.perf_counter() - t0) * 1000
            answers = {k: a.model_dump() for k, a in resp.answers.items()}
            result = JudgeResult(answers, resp.model, resp.usage.input_tokens or 0, latency_ms)
            span.set_attribute("jev.input_tokens", result.input_tokens)
            span.set_attribute("jev.model", resp.model)

        record = {"answers": answers, "model": resp.model, "input_tokens": result.input_tokens, "latency_ms": latency_ms}
        if self.cache_dir:
            (self.cache_dir / f"{key}.json").write_text(json.dumps({**record, "payload": payload}, default=str))
        if self.payload_log:
            with self.payload_log.open("a") as f:
                f.write(json.dumps({"key": key, "payload": payload, **record}, default=str) + "\n")
        return result

    async def aclose(self) -> None:
        await self._client.aclose()


class FakeJudge:
    """Test double. `fn(state, question_id, question_dict) -> answer dict`. Never used in evaluation reports."""

    def __init__(self, fn: Callable[[Any, str, dict], dict], delay_s: float = 0.0, fail: bool = False):
        self.fn, self.delay_s, self.fail = fn, delay_s, fail
        self.calls: list[dict] = []

    async def ask(self, state, questions, *, timeout_s=None) -> JudgeResult:
        payload = _payload("fake", state, questions)
        self.calls.append(payload)
        if self.delay_s:
            if timeout_s is not None and self.delay_s > timeout_s:
                await asyncio.sleep(timeout_s)
                raise JudgeError("timeout")
            await asyncio.sleep(self.delay_s)
        if self.fail:
            raise JudgeError("simulated failure")
        answers = {k: self.fn(state, k, q) for k, q in payload["questions"].items()}
        return JudgeResult(answers, "fake", 0, self.delay_s * 1000)
