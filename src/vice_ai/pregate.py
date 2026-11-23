"""Checks that need no model: bounds, de-duplication, and secret handling.

Runs before anything is sent anywhere. Text that looks like a credential never leaves
the machine: whole-event secrets are rejected and embedded ones are masked.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import OrderedDict
from dataclasses import dataclass

from .config import Config
from .types import AmbientEvent

_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test|proj|ant)?[-_]?[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),  # JWT
    re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*\S+"),
]
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_BARE_TOKEN = re.compile(r"^\S+$")
_NON_LINGUISTIC = re.compile(r"^(?:#?[0-9a-fA-F]{3,8}|[\d\s.,:+\-/%$€£()]+)$")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _entropy(s: str) -> float:
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def redact(text: str) -> tuple[str, int]:
    n = 0
    for pat in _SECRET_PATTERNS:
        text, k = pat.subn("[REDACTED]", text)
        n += k

    def card(m: re.Match) -> str:
        nonlocal n
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            n += 1
            return "[REDACTED]"
        return m.group()

    return _CARD.sub(card, text), n


@dataclass
class PreGateOutcome:
    ok: bool
    reason: str
    event: AmbientEvent | None = None
    redactions: int = 0


class PreGate:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._seen: OrderedDict[str, float] = OrderedDict()

    def check(self, event: AmbientEvent) -> PreGateOutcome:
        text = event.text.strip()
        if len(text) < self.cfg.min_chars:
            return PreGateOutcome(False, "too_short")
        if _NON_LINGUISTIC.match(text):
            return PreGateOutcome(False, "non_linguistic")
        # A single long high-entropy token is most likely a password or key.
        if _BARE_TOKEN.match(text) and len(text) >= 12 and "://" not in text and _entropy(text) > 3.5:
            return PreGateOutcome(False, "probable_secret")

        text, n = redact(text)
        if n and len(text.replace("[REDACTED]", "").strip()) < self.cfg.min_chars:
            return PreGateOutcome(False, "secret_only", redactions=n)

        if len(text) > self.cfg.max_chars:
            # Cut at a line or word boundary so the tail is not a half-token.
            cut = text[: self.cfg.max_chars]
            text = cut[: max(cut.rfind("\n"), cut.rfind(" "), self.cfg.max_chars // 2)]

        digest = hashlib.sha1(text.encode()).hexdigest()
        for k in [k for k, ts in self._seen.items() if event.ts - ts > self.cfg.dedupe_window_s]:
            del self._seen[k]
        # A repeated query is asked again on purpose; only passive triggers (evaluation
        # dataset) are deduplicated.
        if event.trigger not in ("ask", "hook", "mcp", "palette"):
            if digest in self._seen:
                return PreGateOutcome(False, "duplicate")
            self._seen[digest] = event.ts

        cleaned = AmbientEvent(event.id, event.trigger, text, event.ts, event.meta)
        return PreGateOutcome(True, "ok", cleaned, n)
