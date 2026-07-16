from __future__ import annotations

import json
from typing import Any


def render_json(value: Any) -> str:
    """JSON-serialize a value, falling back to its ``str()`` when not serializable."""
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(str(value), ensure_ascii=False)


def truncate_chars(text: str, max_chars: int) -> str:
    """Cap ``text`` at ``max_chars`` and append a ``[truncated N chars]`` note.

    ``max_chars <= 0`` returns ``text`` unchanged (unlimited).
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    removed = len(text) - max_chars
    return f"{text[:max_chars]}\n[truncated {removed} chars]"
