"""What a record says about the element a call acted on.

A uid names one element in one document, so a line reading ``uid=e6600005`` is unusable
by anything that reads the log afterwards. The descriptor is what makes it readable, and
it is taken from the measurement the action already makes: nothing here may cost a page
call.

The value that travels beside that descriptor is the other half, and it lives in
:mod:`tests.test_telemetry_redaction`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from camoufox_mcp.telemetry import MAX_ARG_CHARS
from tests.helpers import extract_uid, last_telemetry_record, open_and_snapshot

# ``NAME_CAP`` in ``dom/js/20_names.js``: how much of any one name the page sends back.
NAME_CAP = 80

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client


async def test_a_click_records_the_element_it_resolved(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """``uid=e6600005`` names nothing in any later document; role and text do.

    Both addresses are exercised, because they are 2 different arms of the resolution
    and only 1 of them starts with a uid.
    """
    profile = "telem_target"
    snapshot = await open_and_snapshot(client, f"{flask_server}/click", profile)
    uid = extract_uid(snapshot, "Click me")
    log_file = data_dir / "logs" / f"{profile}.jsonl"

    await client.call_tool("click", {"profile": profile, "uid": uid})
    assert last_telemetry_record(log_file)["targets"] == [
        {"uid": uid, "tag": "button", "role": "button", "text": "Click me", "resolved": True}
    ]

    await client.call_tool("click", {"profile": profile, "selector": "#btn-counter"})
    targets = last_telemetry_record(log_file)["targets"]
    assert len(targets) == 1
    # The selector arm records the address it was given AND the element it bound to.
    assert targets[0]["selector"] == "#btn-counter"
    assert re.fullmatch(r"e\d+", targets[0]["uid"])
    assert targets[0]["role"] == "button"
    assert targets[0]["text"] == "Count clicks"


async def test_a_secret_word_past_the_name_cap_is_still_read(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """The names the secret test reads are not the name a line renders.

    "Pour valider la création de votre compte, veuillez confirmer ci-dessous votre mot de
    passe" says "passe" at offset 85, and every name used to be capped at 80 characters
    before the test was given them: the one word making the field a secret was cut off,
    the field read as an ordinary text box, and the typed password went to the log in
    clear. The cap belongs to what is RENDERED, which is why ``label`` is still capped.
    """
    profile = "telem_long_label"
    snapshot = await open_and_snapshot(client, f"{flask_server}/secrets", profile)
    uid = extract_uid(snapshot, "veuillez confirmer ci-dessous")

    await client.call_tool("fill", {"profile": profile, "uid": uid, "value": "azerty1234"})

    record = last_telemetry_record(data_dir / "logs" / f"{profile}.jsonl")
    assert record["args"]["value"] == "<redacted 10 chars>"
    target = record["targets"][0]
    assert target["secret"] is True
    # A text input: the word list carried this one on its own, past the cap.
    assert target["input_type"] == "text"
    assert len(target["label"]) == 80


async def test_a_page_controlled_descriptor_cannot_grow_the_line(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """A target's fields cannot be sized by the page, nor by the caller.

    ``role`` is a bare attribute the document writes, and it used to reach the line
    straight off the element with nothing but the Python-side ceiling in the way — which
    is too late: the whole 65,000 characters crossed the protocol first, on every poll
    iteration of the action. It is capped in the page now, like every other name.

    The caller-written half of the same object keeps the ceiling as its only bound: a
    selector is noted before any page work, so nothing else is in a position to cap it.
    """
    profile = "telem_role_cap"
    await client.call_tool("navigate", {"url": f"{flask_server}/secrets", "profile": profile})
    size = MAX_ARG_CHARS + 5000
    await client.call_tool(
        "evaluate",
        {
            "profile": profile,
            "script": f"document.getElementById('promo').setAttribute('role', 'r'.repeat({size}))",
        },
    )

    await client.call_tool("click", {"profile": profile, "selector": "#promo"})
    record = last_telemetry_record(data_dir / "logs" / f"{profile}.jsonl")
    assert record["targets"][0]["role"] == "r" * NAME_CAP

    padded = "#promo" + ":not(#zzz)" * 1500
    await client.call_tool("click", {"profile": profile, "selector": padded})
    record = last_telemetry_record(data_dir / "logs" / f"{profile}.jsonl")
    assert record["targets"][0]["selector"] == padded[:MAX_ARG_CHARS] + f"...[{len(padded)} chars]"
