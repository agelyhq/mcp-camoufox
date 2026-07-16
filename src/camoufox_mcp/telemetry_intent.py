from __future__ import annotations

import hashlib
import re
from typing import Any

# Coarse intent buckets for `evaluate` scripts, matched by cheap regexes. Ordering
# is FIRST-MATCH by descending action strength: a script that both clicks and reads
# is a "click". The order is: click -> state -> style -> wait -> read -> other, so
# the most side-effectful intent wins and pure reads are the last specific bucket.
_INTENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # click: explicit element activation or synthetic event dispatch.
    ("click", re.compile(r"\.click\s*\(|dispatchEvent")),
    # state: storage, cookies, history navigation, or a global assignment (side effect).
    (
        "state",
        re.compile(
            r"localStorage|sessionStorage|document\.cookie|"
            r"history\.(?:pushState|replaceState|go|back|forward)|"
            r"(?:window|globalThis)\.\w+\s*=(?!=)"
        ),
    ),
    # style: inline-style writes, computed-style reads, or class mutations.
    ("style", re.compile(r"\.style\.|getComputedStyle|classList")),
    # wait: timers / animation frames used to poll or defer.
    ("wait", re.compile(r"setTimeout|setInterval|requestAnimationFrame|requestIdleCallback")),
    # read: DOM text extraction or a bare selector lookup (no action matched above).
    (
        "read",
        re.compile(r"innerText|textContent|innerHTML|querySelector|getElementById|getElementsBy"),
    ),
)

# Emptied string literals: single, double, or backtick delimited.
_STRING_LITERAL = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`")
# Numeric literals (ints/floats/hex) collapsed to 0 so magnitudes don't fork the hash.
_NUMBER_LITERAL = re.compile(r"\b0[xX][0-9a-fA-F]+\b|\b\d[\d_]*(?:\.\d+)?\b")
_WHITESPACE = re.compile(r"\s+")


def classify_intent(script: str) -> str:
    """Return the first matching intent bucket, or ``"other"`` when none match."""
    for name, pattern in _INTENT_PATTERNS:
        if pattern.search(script):
            return name
    return "other"


def script_fingerprint(script: str) -> str:
    """12-char sha1 of the script with literals emptied and whitespace collapsed.

    Emptying string literals and zeroing numbers makes near-identical scripts (same
    shape, different selector text or magic numbers) hash to the same fingerprint.
    """
    normalized = _STRING_LITERAL.sub("", script)
    normalized = _NUMBER_LITERAL.sub("0", normalized)
    normalized = _WHITESPACE.sub(" ", normalized).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def evaluate_analytics(script: str) -> dict[str, Any]:
    """Build the evaluate-only telemetry fields for one script."""
    return {
        "intent": classify_intent(script),
        "script_hash": script_fingerprint(script),
        "script_len": len(script),
    }
