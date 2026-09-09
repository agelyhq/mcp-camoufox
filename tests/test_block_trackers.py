"""``block_trackers=false``, measured on the browser rather than on the launch kwargs.

What we hand Camoufox is asserted in :mod:`tests.test_launch_kwargs`, and a kwarg says
nothing about what Firefox did with it. This module drives the public surface and reads
three independent witnesses back out of the browser itself:

* a request uBlock Origin blocks by default (``/fbevents.js``, served by the suite's own
  Flask so the run stays offline) goes through, seen the way an agent sees it, through
  ``list_network_requests``, and corroborated by the script having actually EXECUTED;
* the browser's own extension records name uBlock Origin in one arm and not in the other,
  while the addon this server installs itself survives both;
* the profile's ``prefs.js`` carries Firefox's tracking-protection prefs turned off in one
  arm and untouched in the other.

Everything here is a MATCHED PAIR on two profile names, and that is not a stylistic
choice. uBlock Origin is not armed on the first navigation after a launch (measured: 0 of
31 candidate paths blocked on the first attempt, 9 of 31 after a reload), so a single
navigation asserting "the request went through" passes with the flag on AND off and proves
nothing; and the flag applies at a profile's first launch only, with a pref effect that
outlives the session, so the second arm cannot reuse the first arm's profile.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from typing import TYPE_CHECKING

import pytest

from tests.helpers import PROFILE, evaluate, open_page, server_for, tool_text
from tests.probes import UBO_ID, extensions_after_closing
from tests.waits import completed_entry, poll_tool_or_last, poll_until

if TYPE_CHECKING:
    from pathlib import Path

    from fastmcp import Client, FastMCP

# Reproduced blocked twice on fresh profiles with uBlock Origin loaded, and loaded with it
# excluded, on a 127.0.0.1 origin: the catching filter is filename-generic rather than
# domain-anchored. The alternatives are the other 8 paths that measured the same way, and
# they are named in the failure message so a change in upstream's lists is a 2-minute fix
# rather than an afternoon.
TRACKER_PATH = "/fbevents.js"
MEASURED_ALTERNATIVES = (
    "/gtag/js, /googletagmanager/gtm.js, /en_US/fbevents.js, /prebid.js, "
    "/matomo.js, /piwik.js, /ad/300x250.gif, /ads/300x250.gif"
)

# Generous on purpose: it bounds a browser that never arms its blocker, it does not encode
# how fast the runner is. Each poll costs a real reload, so expiry means many attempts.
ARMING_DEADLINE_S = 90.0
# Reloads the claim arm does BEYOND the number the control needed. The control measures
# when uBlock Origin comes up on this machine; the claim then has to survive strictly more
# than that, so "it just had not armed yet" cannot explain the pass.
EXTRA_RELOADS = 2

CONTROL_PROFILE = "trackers-on"
CLAIM_PROFILE = "trackers-off"

# The id of the do-nothing extension this suite installs through CAMOUFOX_ADDON_URLS, in
# the place of the project's own default addon. See the ``standin_addon`` fixture.
STANDIN_ADDON_ID = "suite-standin@camoufox-mcp.test"

# The 4 preferences MEASURED to change something in this build: they survive a clean
# shutdown into prefs.js, which Firefox only does for a user value that differs from the
# default. The other 3 keys the server sends are already false before we send them, so Firefox
# drops them and asserting on them would fail against a correct implementation — but from two
# different sources: privacy.trackingprotection.enabled from camoufox's own camoufox.cfg, and
# .socialtracking.enabled / .emailtracking.enabled from Firefox's defaults in this build, which
# camoufox.cfg never names at all.
BITING_PREFS = {
    "network.cookie.cookieBehavior": "0",
    "privacy.trackingprotection.annotate_channels": "false",
    "privacy.trackingprotection.fingerprinting.enabled": "false",
    "privacy.trackingprotection.cryptomining.enabled": "false",
}

_USER_PREF = re.compile(r'user_pref\("([^"]+)", (.+?)\);')


@pytest.fixture
def standin_addon(tmp_path: Path) -> str:
    """An addon of ours, built here and served off disk so the run needs no network.

    Decision 3 is that ``block_trackers=false`` removes Camoufox's bundled uBlock Origin
    and never the addon this server installs itself. What carries that addon is the
    ``addons`` launch kwarg, fed by ``CAMOUFOX_ADDON_URLS``; the identity of the URL in
    the default is pinned by :mod:`tests.test_config`. Standing an inert extension in for
    it exercises the same path with the same kwarg while keeping this test offline and
    independent of addons.mozilla.org being reachable, which the real default is not.
    """
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as xpi:
        xpi.writestr(
            "manifest.json",
            json.dumps(
                {
                    "manifest_version": 2,
                    "name": "Suite Stand-In",
                    "version": "1.0",
                    "browser_specific_settings": {"gecko": {"id": STANDIN_ADDON_ID}},
                }
            ),
        )
    path = tmp_path / "standin-addon.xpi"
    path.write_bytes(archive.getvalue())
    return f"file://{path}"


@pytest.fixture
def mcp_server(data_dir: Path, monkeypatch: pytest.MonkeyPatch, standin_addon: str) -> FastMCP:
    """The suite's server with our own addon replaced by the offline stand-in."""
    return server_for(monkeypatch, data_dir, CAMOUFOX_ADDON_URLS=standin_addon)


def _status_of(entry_line: str) -> str:
    """The status field of a ``list_network_requests`` line.

    A uBlock Origin block reaches Playwright as ``requestfailed`` with
    ``NS_ERROR_ABORT``, which this server records as status ``failed`` (code 0),
    indistinguishable from a genuine network error. So the assertion is on failed vs 200
    and never on error text.
    """
    return entry_line.split()[2]


def _user_prefs(data_dir: Path, profile: str) -> dict[str, str]:
    """Every user-branch preference the profile kept, read after a clean shutdown."""
    text = (data_dir / "profiles" / profile / "prefs.js").read_text(encoding="utf-8")
    return dict(_USER_PREF.findall(text))


async def _reload_and_read_entry(client: Client, profile: str) -> str | None:
    """Reload, then wait for this document's tracker request to reach a final status.

    The listing is polled rather than napped on: the per-tab network monitor is fed by
    protocol events, so the entry appears after the navigation returns and a fixed sleep
    would either shorten the run into a false red or lengthen it for nothing.
    """
    await client.call_tool("reload", {"profile": profile})
    listing = await poll_tool_or_last(
        client,
        "list_network_requests",
        {"profile": profile, "resource_types": ["script"]},
        lambda text: completed_entry(text, TRACKER_PATH) is not None,
    )
    return completed_entry(listing, TRACKER_PATH)


async def test_a_blocked_tracker_request_goes_through_with_block_trackers_false(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """The proof: the same request, blocked by the default profile, served to the other.

    Reverting the feature turns the claim arm into a copy of the control arm, and every
    assertion below flips: the request fails, the script never runs, uBlock Origin is
    named in the extension records and no tracking-protection pref is written.
    """
    # The claim browser is launched FIRST and left alive while the control arms. uBlock
    # Origin comes up on wall-clock time as much as on page loads, so matching reload
    # counts alone lets a browser that simply had not armed yet read exactly like a
    # browser that has nothing to arm: measured, an earlier ordering of this test passed
    # against a deliberately reverted implementation. By the time the control blocks, this
    # browser has been alive strictly longer than the control needed, and only then is it
    # asked to reload.
    await client.call_tool(
        "navigate",
        {"profile": CLAIM_PROFILE, "url": f"{flask_server}/tracker", "block_trackers": False},
    )
    await open_page(client, f"{flask_server}/tracker", CONTROL_PROFILE)

    reloads = 0

    async def reload_the_control() -> str | None:
        nonlocal reloads
        reloads += 1
        return await _reload_and_read_entry(client, CONTROL_PROFILE)

    entry, blocked = await poll_until(
        reload_the_control,
        lambda line: line is not None and _status_of(line) == "failed",
        deadline=ARMING_DEADLINE_S,
    )
    assert blocked, (
        f"uBlock Origin never blocked {TRACKER_PATH} on a localhost origin in {reloads} "
        f"reloads: the premise of this proof is gone, not the feature. Last entry: "
        f"{entry!r}. Paths measured to block the same way: {MEASURED_ALTERNATIVES}."
    )
    assert await evaluate(client, CONTROL_PROFILE, "window.__tracker_loaded === true") == "false"

    for attempt in range(reloads + EXTRA_RELOADS):
        claim = await _reload_and_read_entry(client, CLAIM_PROFILE)
        assert claim is not None and _status_of(claim) == "200", (
            f"{TRACKER_PATH} did not go through on reload {attempt + 1} with "
            f"block_trackers=false, after the control needed {reloads}: {claim!r}"
        )
        assert await evaluate(client, CLAIM_PROFILE, "window.__tracker_loaded === true") == "true"

    # Last, because it ends the two browsers everything above measured, and their own
    # records are what turn "the request went through" into "these protections were off".
    assert await extensions_after_closing(client, data_dir, CONTROL_PROFILE) == sorted(
        [STANDIN_ADDON_ID, UBO_ID]
    )
    assert await extensions_after_closing(client, data_dir, CLAIM_PROFILE) == [STANDIN_ADDON_ID]

    control_prefs = _user_prefs(data_dir, CONTROL_PROFILE)
    claim_prefs = _user_prefs(data_dir, CLAIM_PROFILE)
    assert not set(BITING_PREFS) & set(control_prefs), (
        f"the default profile carries tracking-protection preferences of ours: "
        f"{ {k: control_prefs[k] for k in BITING_PREFS if k in control_prefs} }"
    )
    assert {key: claim_prefs.get(key) for key in BITING_PREFS} == BITING_PREFS


async def test_block_trackers_is_ignored_on_an_already_running_profile(
    client: Client, flask_server: str, data_dir: Path
) -> None:
    """A session-creation option arriving late is named in the note and changes nothing.

    The note alone would pass on a server that also applied the flag, so the browser is
    asked afterwards: it still held uBlock Origin, which is exactly what the flag would
    have removed had it been honoured.
    """
    await open_page(client, f"{flask_server}/tracker")

    second = tool_text(
        await client.call_tool(
            "navigate",
            {"profile": PROFILE, "url": f"{flask_server}/", "block_trackers": False},
        )
    )

    assert "(options ignored: block_trackers; session already active)" in second
    assert await extensions_after_closing(client, data_dir) == sorted([STANDIN_ADDON_ID, UBO_ID])
