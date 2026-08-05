"""Auto-waiting survived the move off the driver's selector engine.

Resolving a selector with one synchronous query would turn every asynchronously
rendered page into an instant "no element matches". The Python-side poll is what
replaces it, and it also bounds the operations that were previously uncapped.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from camoufox_mcp.dom.waiting import EVAL_TIMEOUT
from tests.helpers import (
    PROFILE,
    call_within,
    extract_uid,
    open_and_snapshot,
    open_page,
    text_content,
    tool_text,
)

if TYPE_CHECKING:
    from fastmcp import Client

# Guardrails, not measurements: each one is a multiple of the budget the product
# actually promises, and only a call that never comes back reaches them.
_EXPIRY_GUARDRAIL_S = 20.0
_GUARDRAIL_MARGIN_S = 30.0


async def test_click_selector_waits_for_a_late_element(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/waiting")

    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": "#late-btn"})
    )

    assert result.startswith("Clicked <button>"), result
    assert "#late-btn" in result
    assert "late button clicked" in await text_content(client, PROFILE, "late-output")


async def test_fill_selector_waits_for_a_late_field(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/waiting")

    result = tool_text(
        await client.call_tool(
            "fill", {"profile": PROFILE, "selector": "#late-field", "value": "hello"}
        )
    )

    assert result.startswith("Filled <input>"), result
    assert "late field: hello" in await text_content(client, PROFILE, "late-output")


async def test_click_selector_expiry_message(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/waiting")

    result = await call_within(
        client, "click", {"profile": PROFILE, "selector": "#never"}, _EXPIRY_GUARDRAIL_S
    )

    assert result == (
        "Error: ValueError: no element matches selector '#never'; nothing matched at any "
        "point during the 5s wait, so check the selector, or wait for it first with "
        "wait_for(condition='selector', timeout=<ms>)"
    )


async def test_unsupported_selector_syntax_is_named(client: Client, flask_server: str) -> None:
    """A syntax we do not reimplement must say so, not silently match nothing."""
    await open_page(client, f"{flask_server}/waiting")

    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": "#a >> #b"})
    )

    assert "invalid selector '#a >> #b'" in result
    assert "chained engines (>>) is not supported" in result
    assert 'plain CSS, :has-text("..."), text=...' in result

    engine = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": "role=button"})
    )
    assert "the role= engine is not supported" in engine


async def test_attribute_selectors_are_not_mistaken_for_engines(
    client: Client, flask_server: str
) -> None:
    """`[role=...]` and `[data-testid=...]` are ordinary CSS and must keep working."""
    await open_page(client, f"{flask_server}/click")

    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": '[id="btn-counter"]'})
    )
    assert result.startswith("Clicked <button>"), result

    missing = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": '[data-testid="none"]'})
    )
    assert missing.startswith(
        "Error: ValueError: no element matches selector '[data-testid=\"none\"]'; "
    ), missing
    assert "nothing matched at any point during the 5s wait" in missing, missing


async def test_has_text_selector_filters_matches(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/click")

    result = tool_text(
        await client.call_tool(
            "click", {"profile": PROFILE, "selector": 'button:has-text("Count clicks")'}
        )
    )

    assert result.startswith("Clicked <button>"), result
    assert "1" in await text_content(client, PROFILE, "counter-output")


async def test_text_selector_matches_by_text_alone(client: Client, flask_server: str) -> None:
    await open_page(client, f"{flask_server}/click")

    result = tool_text(
        await client.call_tool("click", {"profile": PROFILE, "selector": "text=Count clicks"})
    )

    assert result.startswith("Clicked <button>"), result
    assert "1" in await text_content(client, PROFILE, "counter-output")


async def test_op_timeout_renders_as_timeout(client: Client, flask_server: str) -> None:
    """The one operation allowed to await is still bounded by a real clock.

    The message names the budget, so the fixed result is what the caller is told. The
    lower bound stays because it is one-sided: a busier machine only makes it bigger,
    and the failure it catches is a script abandoned early. The upper bound moved into
    the guardrail, where a script that never comes back fails loudly instead of being
    scored against how fast the runner is.
    """
    snap = await open_and_snapshot(client, f"{flask_server}/click")
    uid = extract_uid(snap, "Click me")

    started = time.monotonic()
    result = await call_within(
        client,
        "evaluate",
        {"profile": PROFILE, "script": "() => new Promise(() => {})", "uids": [uid]},
        EVAL_TIMEOUT + _GUARDRAIL_MARGIN_S,
    )
    elapsed = time.monotonic() - started

    assert result == f"Timeout: page script did not answer within {EVAL_TIMEOUT:g}s", result
    assert elapsed > EVAL_TIMEOUT - 5, f"the evaluate budget expired after {elapsed:.1f}s"
