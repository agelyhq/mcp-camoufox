from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp.dom import PollExpiredError, locate_visible, poll_until
from camoufox_mcp.tools._base import DEFAULT_TIMEOUT_MS, get_page, get_session, tool
from camoufox_mcp.tools._errors import validate_choice
from camoufox_mcp.tools._text import render_capped

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.dom import RegistryPage
    from camoufox_mcp.tools._base import ToolDeps

_VALID_CONDITIONS = ("load", "selector", "network_idle", "predicate")

# Both values this tool reports come from a caller-supplied expression, so they answer
# to the caps `evaluate` answers to: uncapped, an innerHTML return is unbounded, and a
# node comes back as the raw "ref: <Node>" marker instead of the refusal it deserves.
_DEFAULT_MAX_CHARS = 20000
_MAX_ITEMS = 200


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def wait_for(
        profile: str,
        condition: str,
        selector: str | None = None,
        expression: str | None = None,
        return_expression: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_MS,
        max_chars: int = _DEFAULT_MAX_CHARS,
    ) -> str:
        """Wait for a page condition, instead of polling with ``evaluate``.

        Args:
            condition: "load" (the document load event), "network_idle" (no network
                connection for 500 ms), "selector" (``selector`` has a visible match)
                or "predicate" (``expression`` returns truthy). The last 2 are polled
                every 50 ms.
            expression: JS expression that must become truthy, e.g.
                ``"window.__appReady === true"``. On expiry its last value is reported.
            return_expression: Evaluated once after the wait succeeds; its JSON result
                is appended to the confirmation.
            timeout: Maximum wait in milliseconds.
            max_chars: Cap on a reported value (``<= 0`` unlimited).
        """
        validate_choice("condition", condition, _VALID_CONDITIONS)

        session = await get_session(deps, profile)
        page = get_page(session)

        if condition == "selector":
            base = await _wait_selector(page, selector, timeout)
        elif condition == "predicate":
            base = await _wait_predicate(page, expression, timeout, max_chars)
        else:
            state = "load" if condition == "load" else "networkidle"
            await page.raw.wait_for_load_state(state, timeout=timeout)
            base = f"Condition met: {condition}"

        if return_expression:
            returned = await page.evaluate(return_expression)
            base += f" => {render_capped(returned, max_chars, _MAX_ITEMS)}"
        return base


async def _wait_selector(page: RegistryPage, selector: str | None, timeout: int) -> str:
    if not selector:
        raise ValueError("condition 'selector' requires a non-empty selector")
    # mint=False: waiting for something to appear should not consume a uid number.
    found = await locate_visible(page, selector, deadline=timeout / 1000, mint=False)
    if found is None:
        raise TimeoutError(f"selector '{selector}' did not appear within {timeout}ms")
    return f"Condition met: selector ({selector})"


async def _wait_predicate(
    page: RegistryPage, expression: str | None, timeout: int, max_chars: int
) -> str:
    if not expression:
        raise ValueError("condition 'predicate' requires a non-empty expression")

    async def probe() -> Any:
        return await page.evaluate(expression)

    try:
        await poll_until(probe, bool, deadline=timeout / 1000)
    except PollExpiredError as expired:
        last = render_capped(expired.last, max_chars, _MAX_ITEMS)
        raise TimeoutError(f"predicate stayed falsy for {timeout}ms; last value: {last}") from None
    return "Condition met: predicate"
