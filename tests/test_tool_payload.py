"""The tool surface is a per-conversation cost, so it is measured like one.

Every check here runs against the payload the in-process server actually serialises,
never against a stored copy of itself: a test that compares the baseline to the
baseline passes forever and protects nothing.

The budget, the component breakdown and what to do when this fails all live in
``tests/payload_baseline.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import Client

BASELINE_PATH = Path(__file__).parent / "payload_baseline.json"
BASELINE: dict[str, Any] = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

# Below this the instructions cannot still carry the doctrine the 27 docstrings gave
# up: profiles, uid lifetime, selector syntax, the observe modes, the error contract.
INSTRUCTION_FLOOR = 1500


def _compact(value: Any) -> str:
    # ensure_ascii=False so the count is the UTF-8 text a client reads, and so a
    # stray em dash shows up as itself rather than as an escape sequence.
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


async def _payload(client: Client) -> tuple[str, list[Any]]:
    """The serialised tools/list response, exactly as a client receives it."""
    tools = await client.list_tools()
    dumped = [tool.model_dump(exclude_none=True) for tool in tools]
    return _compact(dumped), dumped


def _components(dumped: list[dict[str, Any]]) -> dict[str, int]:
    """Where the bytes are, so a regression can be attributed, not just detected."""
    descriptions = sum(len(tool.get("description") or "") for tool in dumped)
    params = sum(
        len(prop.get("description") or "")
        for tool in dumped
        for prop in (tool.get("inputSchema") or {}).get("properties", {}).values()
    )
    output = sum(len(_compact(tool["outputSchema"])) for tool in dumped if "outputSchema" in tool)
    meta = sum(len(_compact(tool["meta"])) for tool in dumped if "meta" in tool)
    return {
        "tool_description_chars": descriptions,
        "param_description_chars": params,
        "output_schema_chars": output,
        "meta_chars": meta,
    }


async def test_tool_payload_within_budget(client: Client) -> None:
    """The live tools/list payload stays within the agreed margin over the baseline."""
    blob, dumped = await _payload(client)
    budget = round(BASELINE["payload_chars"] * (1 + BASELINE["margin"]))
    breakdown = _components(dumped)
    structural = len(blob) - sum(breakdown.values())
    report = (
        f"payload {len(blob)} chars over {len(dumped)} tools "
        f"(baseline {BASELINE['payload_chars']}, budget {budget}); "
        + ", ".join(f"{name} {size}" for name, size in breakdown.items())
        + f", structural_chars {structural}"
    )
    print(report)
    assert len(blob) <= budget, f"{report}. Read {BASELINE_PATH.name} before changing it."


async def test_tool_count_matches_baseline(client: Client) -> None:
    """A tool added or removed invalidates the budget, so the count is pinned too."""
    _, dumped = await _payload(client)
    assert len(dumped) == BASELINE["tools"], (
        f"{len(dumped)} tools registered, baseline records {BASELINE['tools']}; "
        f"re-measure and update {BASELINE_PATH.name}."
    )


async def test_no_em_dash_in_the_tool_surface(client: Client) -> None:
    """No em dash reaches the client: the surface is written in plain ASCII prose."""
    blob, _ = await _payload(client)
    assert "—" not in blob


async def test_server_instructions_are_served(client: Client) -> None:
    """The shared doctrine reaches the client, or 27 docstrings lost it for nothing.

    The instructions carry what every tool used to repeat: profile isolation, uid
    lifetime, selector syntax, the observe modes and the one-line error contract. A
    refactor that drops them silently would leave the agent with neither copy.
    """
    result = client.initialize_result
    assert result is not None
    instructions = result.instructions
    assert instructions, "the server served no instructions"

    # A range, not an exact length: rewording is free, gutting them and inflating
    # them are not. They are paid once per conversation, like the tool payload.
    baseline = BASELINE["server_instruction_chars"]
    ceiling = round(baseline * (1 + BASELINE["margin"]))
    assert INSTRUCTION_FLOOR <= len(instructions) <= ceiling, (
        f"instructions are {len(instructions)} chars, expected between "
        f"{INSTRUCTION_FLOOR} and {ceiling} (baseline {baseline}); "
        f"update {BASELINE_PATH.name} if the change is deliberate."
    )
    for topic in (
        "ProfileInUseError",
        "stale uid",
        "observe=",
        ':has-text("...")',
        "Error: <Type>",
    ):
        assert topic in instructions, f"the instructions no longer mention {topic!r}"


async def test_the_observe_bullet_states_the_cost_not_only_the_win(client: Client) -> None:
    """``observe`` is the one parameter that spends the result budget, so it is priced.

    It used to be sold as "replaces the follow-up snapshot call, halving the round
    trips", with nothing said about the chars that arrive instead. An agent reading
    only the win has no reason ever to pass "none". The bullet must therefore carry
    all 3 parts of the trade: what it adds, what happens when the page is bigger than
    that, and when not to pay. Rewording is free; dropping a part is not.
    """
    result = client.initialize_result
    assert result is not None
    bullets = [line for line in (result.instructions or "").split("\n- ") if "`observe`" in line]
    assert len(bullets) == 1, "the observe trade must be stated in exactly 1 place"
    bullet = bullets[0]

    for part, what in (
        ("4000", "the size an observation adds to the result"),
        ("truncated", "what happens past that size"),
        ('observe="none"', "the way to opt out"),
    ):
        assert part in bullet, f"the observe bullet no longer states {what}: {bullet!r}"
