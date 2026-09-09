"""What a value typed into a page may leave behind, and where it must not.

A password must not reach the disk, and a search term must: over-redaction is the
failure this file exists to catch, which is why a discount code is filled here on
purpose. Every route out of a fill is covered, because ``args`` is the only field
redaction rewrites — a value quoted into the note, the observation or the refusal is on
the same line, in clear.

The descriptor that travels beside the value lives in
:mod:`tests.test_telemetry_targets`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import (
    STALE_UID,
    evaluate,
    extract_uid,
    last_telemetry_record,
    open_and_snapshot,
    snapshot_text,
    tool_text,
)

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client


async def test_a_secret_field_is_redacted_and_a_legitimate_one_is_not(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """Redaction keyed on what resolved, not on the tool that asked.

    The 3 fills are the whole rule: the type the page declares, the French label a type
    cannot declare, and the discount code that must stay legible because a value like it
    is the substance of anything generated from this log.
    """
    profile = "telem_secret"
    snapshot = await open_and_snapshot(client, f"{flask_server}/secrets", profile)
    log_file = data_dir / "logs" / f"{profile}.jsonl"

    password_uid = extract_uid(snapshot, "Password")
    await client.call_tool("fill", {"profile": profile, "uid": password_uid, "value": "hunter2!"})
    record = last_telemetry_record(log_file)
    assert record["args"]["value"] == "<redacted 8 chars>"
    assert record["targets"] == [
        {
            "uid": password_uid,
            "tag": "input",
            "role": "textbox",
            "input_type": "password",
            "label": "Password",
            "resolved": True,
            "secret": True,
        }
    ]

    french_uid = extract_uid(snapshot, "Mot de passe")
    await client.call_tool("fill", {"profile": profile, "uid": french_uid, "value": "azerty1234"})
    record = last_telemetry_record(log_file)
    assert record["args"]["value"] == "<redacted 10 chars>"
    # A type of "text" proves the word list carried this one on its own.
    assert record["targets"][0]["input_type"] == "text"
    assert record["targets"][0]["label"] == "Mot de passe"

    promo_uid = extract_uid(snapshot, "Code promo")
    await client.call_tool("fill", {"profile": profile, "uid": promo_uid, "value": "SUMMER2026"})
    record = last_telemetry_record(log_file)
    assert record["args"]["value"] == "SUMMER2026"
    assert "secret" not in record["targets"][0]


async def test_a_long_search_term_is_logged_whole(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """The value a fill types is the substance of a recipe, and 300 chars is not long."""
    profile = "telem_value"
    snapshot = await open_and_snapshot(client, f"{flask_server}/secrets", profile)
    uid = extract_uid(snapshot, "Search")
    typed = "a" * 300

    await client.call_tool("fill", {"profile": profile, "uid": uid, "value": typed})

    record = last_telemetry_record(data_dir / "logs" / f"{profile}.jsonl")
    assert record["args"]["value"] == typed
    assert record["targets"][0]["input_type"] == "search"


async def test_a_password_is_never_rendered_by_the_page_reads_nor_by_the_record(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """The value of an ``<input type=password>`` is elided where it is RENDERED.

    Raising the result ceiling to 10,000 characters is what made this reachable: the
    observation a fill appends renders a `value=` part for the field it just filled, and
    under the old 200-char cap the byte at offset 225 of that note was simply cut off. The
    same string feeds `snapshot`, `find` and the note, so the elision belongs to the one
    place all three read from — and the agent holding the snapshot has no business seeing
    the password either.
    """
    profile = "telem_pw_render"
    snapshot = await open_and_snapshot(client, f"{flask_server}/secrets", profile)
    uid = extract_uid(snapshot, "Password")
    typed = "hunter2secret"
    elided = f"value=<redacted {len(typed)} chars>"

    filled = tool_text(
        await client.call_tool(
            "fill", {"profile": profile, "uid": uid, "value": typed, "observe": "snapshot"}
        )
    )
    assert typed not in filled
    assert elided in filled

    # The record of that fill, read before anything else appends one: the note is the
    # observation above, and it is where the secret used to land.
    record = last_telemetry_record(data_dir / "logs" / f"{profile}.jsonl")
    assert typed not in record["result"]
    assert record["args"]["value"] == f"<redacted {len(typed)} chars>"

    # The 2 other page reads built from the same renderer.
    assert elided in await snapshot_text(client, profile)
    found = tool_text(
        await client.call_tool("find", {"profile": profile, "css": "#account-password"})
    )
    assert typed not in found
    assert elided in found

    # The other arm of that renderer: a password the page hides behind the <label> that
    # stands for it, which is how a styled control is built. The uid lands on the label,
    # so the value is rendered by the control description and not by the input's own
    # branch — a second place the same rule has to hold. Set from the page, because a
    # fill cannot address a control it can only reach through its label.
    wrapped = "hunter2wrapped"
    await evaluate(
        client, profile, f"document.querySelector('#wrapped-password input').value = '{wrapped}'"
    )
    tree = await snapshot_text(client, profile)
    assert wrapped not in tree
    assert f"control=textbox, name=new_password, value=<redacted {len(wrapped)} chars>" in tree


async def test_a_secret_named_by_a_source_that_loses_the_naming_race_is_redacted(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """A field is named by 4 things, and only 1 of them gets to be its label.

    ``<label for=cvc>Security code</label><input name=cvc>`` is the shape: the bound label
    answers first, and the form name — the only part of that field that says "card
    verification code" — was never consulted. The record still reads "Security code",
    because a label reading "Security code cvc" is worse for whoever reads the log.

    The postal field beside it is the other half of the rule: "PIN Code" is the Indian
    postal code, it is on every shipping form, and it must stay legible.
    """
    profile = "telem_names"
    snapshot = await open_and_snapshot(client, f"{flask_server}/secrets", profile)
    log_file = data_dir / "logs" / f"{profile}.jsonl"

    cvc_uid = extract_uid(snapshot, "Security code")
    await client.call_tool("fill", {"profile": profile, "uid": cvc_uid, "value": "123"})
    record = last_telemetry_record(log_file)
    assert record["args"]["value"] == "<redacted 3 chars>"
    assert record["targets"][0]["label"] == "Security code"
    assert record["targets"][0]["secret"] is True
    # What the test reads is not what the record keeps.
    assert "name_sources" not in record["targets"][0]

    postal_uid = extract_uid(snapshot, "PIN Code")
    await client.call_tool("fill", {"profile": profile, "uid": postal_uid, "value": "560001"})
    record = last_telemetry_record(log_file)
    assert record["args"]["value"] == "560001"
    assert "secret" not in record["targets"][0]


async def test_a_fill_on_a_stale_uid_keeps_its_address_and_drops_its_value(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """The retry an agent makes after a navigation invalidated every uid it held.

    That retry is the one carrying the password the failed call never entered, and the
    project's own docs say a navigation invalidates every uid, so it is not a rare shape.
    Nothing resolved, so nothing says the field was safe, and the value reached no page:
    it is worth nothing to anything generated from this log, while a leaked credential is
    permanent. Everything that makes the failure diagnosable is kept.
    """
    profile = "telem_stale"
    snapshot = await open_and_snapshot(client, f"{flask_server}/secrets", profile)
    log_file = data_dir / "logs" / f"{profile}.jsonl"
    typed = "hunter2stale"

    stale = tool_text(
        await client.call_tool("fill", {"profile": profile, "uid": "e999999", "value": typed})
    )
    assert STALE_UID.format(uid="e999999") in stale
    record = last_telemetry_record(log_file)
    assert record["args"]["value"] == f"<redacted {len(typed)} chars>"
    assert record["args"]["uid"] == "e999999"
    assert record["ok"] is False
    assert "stale uid" in record["error"]
    # Nothing but the address, and the flag saying so in as many words.
    assert record["targets"] == [{"uid": "e999999", "resolved": False}]

    # The other half: a fill that landed on a field nothing calls a secret is still on
    # disk in full, same value, so the rule above cannot be read as "redact fills".
    search_uid = extract_uid(snapshot, "Search")
    await client.call_tool("fill", {"profile": profile, "uid": search_uid, "value": typed})
    assert last_telemetry_record(log_file)["args"]["value"] == typed


async def test_a_refused_fill_never_quotes_the_value_it_was_given(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """Redaction rewrites ``args``; ``error`` and ``result`` are written as they stand.

    Both refusals a fill can raise about the text itself are reachable on a field the
    word list calls a secret — a ``<select>`` whose form name is ``token``, a checkbox
    labelled "Remember this token" — so the value redacted out of ``args`` used to be
    written back onto the same line in clear by the message explaining the refusal. What
    has to survive is the diagnosis: the options that do exist, and the states accepted.
    """
    profile = "telem_refused"
    snapshot = await open_and_snapshot(client, f"{flask_server}/secrets", profile)
    log_file = data_dir / "logs" / f"{profile}.jsonl"
    typed = "hunter2refused"
    elided = f"<{len(typed)} chars>"

    scope_uid = extract_uid(snapshot, "Scope")
    refused = tool_text(
        await client.call_tool("fill", {"profile": profile, "uid": scope_uid, "value": typed})
    )
    assert typed not in refused
    assert elided in refused
    # The refusal still says what would have worked.
    assert "Read and write" in refused
    record = last_telemetry_record(log_file)
    assert record["args"]["value"] == f"<redacted {len(typed)} chars>"
    assert record["targets"][0]["secret"] is True
    assert typed not in record["error"]
    assert typed not in record["result"]

    toggle_uid = extract_uid(snapshot, "Remember this token")
    refused = tool_text(
        await client.call_tool("fill", {"profile": profile, "uid": toggle_uid, "value": typed})
    )
    assert typed not in refused
    assert elided in refused
    assert "'unchecked'" in refused
    record = last_telemetry_record(log_file)
    assert record["args"]["value"] == f"<redacted {len(typed)} chars>"
    assert record["targets"][0]["secret"] is True
    assert typed not in record["error"]
    assert typed not in record["result"]


async def test_a_multi_field_form_redacts_field_by_field(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """One password in a 6-field call must not cost the other 5 their values.

    The values live one level down, inside ``fields[]``, which is where a rule written
    against the top-level argument would miss them entirely.
    """
    profile = "telem_form"
    snapshot = await open_and_snapshot(client, f"{flask_server}/secrets", profile)
    password_uid = extract_uid(snapshot, "Password")
    promo_uid = extract_uid(snapshot, "Code promo")

    await client.call_tool(
        "fill_form",
        {
            "profile": profile,
            "fields": [
                {"uid": promo_uid, "value": "WINTER2026"},
                {"uid": password_uid, "value": "correct horse"},
            ],
        },
    )

    record = last_telemetry_record(data_dir / "logs" / f"{profile}.jsonl")
    assert record["args"]["fields"] == [
        {"uid": promo_uid, "value": "WINTER2026"},
        {"uid": password_uid, "value": "<redacted 13 chars>"},
    ]
    # One descriptor per field, in the order they were filled.
    assert [target["uid"] for target in record["targets"]] == [promo_uid, password_uid]
    assert [target.get("secret") for target in record["targets"]] == [None, True]
