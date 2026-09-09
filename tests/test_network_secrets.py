"""What a captured request may show of a signed-in profile, and what it may not.

``get_network_request`` renders one request as the browser saw it, which is where the
credentials of a hand-established login live: the ``Cookie`` header IS the session, and
a sign-in body carries the very password redaction takes out of ``args``. Both used to
be rendered verbatim into the tool result, which is handed to the model AND written to
the record as ``result``, a field redaction never rewrites.

Every assertion here has 2 halves on purpose: the credential is gone, and the diagnosis
that makes the tool worth calling — the header name, the status, the fields that are not
secrets — is still there. A tool that answers nothing would pass the first half alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.helpers import evaluate, last_telemetry_record, tool_text
from tests.waits import completed_entry, poll_tool_or_last, reqid_for

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client

_BEARER = "Bearer sk-live-4f9c2a7b31e84d6890fb"
_PASSWORD = "hunter2-network"
# Set by /api/login on its way out, so the response header block carries it too.
_SESSION_COOKIE = "s3cr3t-session-value"


async def _post_login(
    client: Client, profile: str, flask_server: str, *, body: str, ctype: str
) -> None:
    """Sign in from the page itself, so the request is captured the way a real one is."""
    await client.call_tool("navigate", {"profile": profile, "url": f"{flask_server}/network"})
    status = await evaluate(
        client,
        profile,
        "(async () => {"
        f"  const r = await fetch('{flask_server}/api/login', {{"
        "    method: 'POST',"
        f"    headers: {{'Content-Type': '{ctype}', 'Authorization': '{_BEARER}'}},"
        f"    body: {body}"
        "  });"
        "  return r.status;"
        "})()",
    )
    assert "200" in status, status


async def _login_detail(client: Client, profile: str) -> str:
    """The rendered detail of the captured sign-in, once it has an answer."""
    listing = await poll_tool_or_last(
        client,
        "list_network_requests",
        {"profile": profile},
        lambda text: completed_entry(text, "/api/login") is not None,
    )
    reqid = reqid_for(listing, "/api/login")
    return tool_text(
        await client.call_tool("get_network_request", {"profile": profile, "reqid": reqid})
    )


async def test_a_captured_login_shows_its_headers_but_none_of_their_credentials(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """The authentication headers and the JSON sign-in body, in the result and the record.

    Raising the result ceiling from 200 to 10,000 characters is what made this worth
    fixing now: the POST section sits after a header block that routinely runs past 200
    characters, so the body used to be cut off before it reached disk and is now recorded
    whole.
    """
    profile = "netsec_json"
    await _post_login(
        client,
        profile,
        flask_server,
        body=f"JSON.stringify({{username: 'alice', password: '{_PASSWORD}'}})",
        ctype="application/json",
    )

    detail = await _login_detail(client, profile)

    # The header the agent needs to know was sent, without the credential it carried.
    assert _BEARER not in detail, detail
    assert "authorization" in detail.lower(), detail
    assert f"<redacted {len(_BEARER)} chars>" in detail, detail
    # The session the server handed back, on the response side of the same rule.
    assert _SESSION_COOKIE not in detail, detail
    assert "set-cookie" in detail.lower(), detail
    # One field of the body goes, and only that one: the rest is why this tool exists.
    assert _PASSWORD not in detail, detail
    assert f'"password":"<redacted {len(_PASSWORD)} chars>"' in detail, detail
    assert '"username":"alice"' in detail, detail
    # The diagnosis, which is the whole point of calling it.
    assert "Status: 200" in detail
    assert "/api/login" in detail
    assert "POST data:" in detail

    # The same string is the record's ``result``, which redaction never rewrites.
    record = last_telemetry_record(data_dir / "logs" / f"{profile}.jsonl")
    assert record["tool"] == "get_network_request"
    assert _BEARER not in record["result"]
    assert _PASSWORD not in record["result"]
    assert _SESSION_COOKIE not in record["result"]
    assert "authorization" in record["result"].lower()
    assert '"username":"alice"' in record["result"]


async def test_a_urlencoded_body_loses_its_secret_field_and_keeps_the_others(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """The other body shape a sign-in takes: a plain HTML form post.

    ``next=%2Fdashboard`` is here to prove the substitution is made in place: an
    untouched field must come back with its percent-encoding exactly as captured, not
    re-serialized by a round trip through a parser.
    """
    profile = "netsec_form"
    await _post_login(
        client,
        profile,
        flask_server,
        body=f"'username=alice&password={_PASSWORD}&next=%2Fdashboard'",
        ctype="application/x-www-form-urlencoded",
    )

    detail = await _login_detail(client, profile)

    assert _PASSWORD not in detail, detail
    assert f"password=<redacted {len(_PASSWORD)} chars>" in detail, detail
    assert "username=alice" in detail, detail
    assert "next=%2Fdashboard" in detail, detail

    # The same string is the record's ``result``, which redaction never rewrites: the
    # tool result is read once, and the line stays on disk.
    record = last_telemetry_record(data_dir / "logs" / f"{profile}.jsonl")
    assert _PASSWORD not in record["result"]
    assert "username=alice" in record["result"]
