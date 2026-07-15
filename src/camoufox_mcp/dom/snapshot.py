from __future__ import annotations

from pathlib import Path

_JS_DIR = Path(__file__).resolve().parent / "js"

_JS_CACHE: dict[str, str] = {}


def _load_js(name: str) -> str:
    if name not in _JS_CACHE:
        _JS_CACHE[name] = (_JS_DIR / name).read_text(encoding="utf-8")
    return _JS_CACHE[name]


def get_snapshot_js() -> str:
    return _load_js("snapshot.js")


def get_resolve_uid_js() -> str:
    return _load_js("resolve_uid.js")


def get_clear_field_js() -> str:
    return _load_js("clear_field.js")


def get_scroll_into_view_js() -> str:
    return _load_js("scroll_into_view.js")


def get_file_input_selector_js() -> str:
    return _load_js("file_input_selector.js")
