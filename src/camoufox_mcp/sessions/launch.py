from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from camoufox_mcp.config import ServerConfig
    from camoufox_mcp.sessions.init_options import SessionInitOptions

IS_LINUX = sys.platform.startswith("linux")

# Camoufox loads its own bundled addons (uBlock Origin, `camoufox.addons.DefaultAddons`)
# into every browser it launches: `launch_options` calls `add_default_addons` unconditionally,
# and the `addons` list this server passes is only appended to that. `exclude_addons` is the
# single way out, which is why `CAMOUFOX_BUNDLED_ADDONS=false` exists: a browser holding an
# extension writes to pages on its own, and the marker suite measures OUR footprint only.

# Humanised cursor movement is opt-in (``CAMOUFOX_HUMANIZE``, off by default): with it
# on, Firefox intermittently stops answering the Juggler protocol part-way through a
# ``Page.dispatchMouseEvent`` while the process stays alive, so the pending click or
# hover never returns. Re-measured 2026-08-03 against a 152.0.4-beta.28 binary that
# already carries the two upstream fixes: a missed hit-renderer acknowledgement still
# wedges a process-global dispatch chain permanently, with no upstream timeline. It has
# happened in production, not only under test: one click_at ran for 2,004,856 ms.
# When enabled, the value MUST reach Camoufox as a float. Camoufox decides whether
# ``humanize`` carries a max cursor-travel time with ``isinstance(humanize, (int,
# float))`` and never excludes bool, which subclasses int, so a plain ``True`` forwards
# ``humanize:maxTime = true``, which Firefox rejects outright ("Value for key
# 'humanize:maxTime' is not a double"). Still true of camoufox 0.5.4.

# Every protection that can block or neuter a tracker request, turned off. Sent ONLY when
# a session is created with ``block_trackers=False``.
#
# Measured against camoufox 0.4.11 / Firefox 152.0.4-beta.28 by diffing the profile's
# ``prefs.js`` after a clean shutdown against a launch that sent nothing: Firefox drops a
# user value equal to the default, so a key that survives is a key that changed something,
# and a control key that exists in no build proved that absence means "already at that
# value" rather than "no such pref". The first 4 bite. The last 3 are already false before we
# send them, but not from the same source: ``privacy.trackingprotection.enabled`` is turned off
# by camoufox's own ``camoufox.cfg`` (line 762), while ``.socialtracking.enabled`` and
# ``.emailtracking.enabled`` appear nowhere in that file and are inert on Firefox's own defaults
# in this build. All 3 are kept anyway, and the second pair is the weaker guarantee of the two:
# a vendor config line changes when the vendor changes it, a Firefox default can flip on any
# Firefox upgrade. Sending them makes the value this server's rather than someone else's.
#
# ``privacy.partition.network_state`` is deliberately absent, and must not be re-added from
# the ``camoufox.cfg`` line that sets it: no code in this build reads that name. ``libxul``
# holds no NUL-terminated copy of it (only the longer ``.connection_with_proxy``), and an
# int fed to it through ``user.js`` survives into ``prefs.js`` exactly like an invented
# name, where every real pref rejects the wrong type. Sending it guarantees nothing; the
# cross-site identity claim is carried entirely by ``network.cookie.cookieBehavior=0``,
# which camoufox.cfg defaults to 4, not 0. Worse, an untyped name takes the type of its
# first setter, and a disagreement with camoufox.cfg's ``defaultPref`` aborts startup:
# measured, a bool there and an int on the user branch never launches the browser at all.
#
# ``browser.contentblocking.category`` is deliberately absent: it is a string
# ("standard"/"strict"/"custom"), and the machinery that would clear these prefs runs at
# ``browser-first-window-ready``, BEFORE Playwright's Juggler transport delivers
# ``firefox_user_prefs`` at ``Browser.enable``. Measured on a profile whose ``prefs.js``
# already said "standard": all 4 biting prefs survived and the category rewrote itself to
# "custom". SafeBrowsing is absent for a simpler reason: ``camoufox.cfg`` already disables all
# 5 of its ``.enabled`` toggles on every launch — ``blockedURIs``, ``downloads``, ``passwords``,
# ``malware`` and ``phishing``, lines 659-663 — and blanks a 6th key,
# ``browser.safebrowsing.provider.mozilla.updateURL``, at line 604, so there is nothing left for
# us to turn off.
#
# Consequence documented, not fixed here: Juggler sets these on the USER branch of a
# persistent profile, so Firefox writes them to ``prefs.js`` at shutdown and they SURVIVE
# later launches that send nothing. A profile created with ``block_trackers=False`` keeps
# Firefox's protections off for good; only the uBlock Origin exclusion is per-launch.
TRACKER_PREFS_OFF: dict[str, Any] = {
    "network.cookie.cookieBehavior": 0,
    "privacy.trackingprotection.annotate_channels": False,
    "privacy.trackingprotection.fingerprinting.enabled": False,
    "privacy.trackingprotection.cryptomining.enabled": False,
    "privacy.trackingprotection.enabled": False,
    "privacy.trackingprotection.socialtracking.enabled": False,
    "privacy.trackingprotection.emailtracking.enabled": False,
}


def build_launch_kwargs(
    config: ServerConfig,
    opts: SessionInitOptions,
    user_data_dir: Path,
    addon_dirs: list[str],
) -> dict[str, Any]:
    """Translate config + resolved session options into Camoufox launch kwargs.

    Always-on: ``persistent_context=True`` and a private ``env`` copy. ``geoip`` is
    forced ``True`` whenever a proxy is configured (Camoufox leaks a warning
    otherwise). ``headless`` uses the per-session override when supplied, else the
    server-wide ``config.headless`` default. ``humanize`` is only sent when
    ``config.humanize`` is set, and ``browser`` only when a build is pinned.
    ``exclude_addons`` is sent when EITHER ``CAMOUFOX_BUNDLED_ADDONS`` is off or the
    session was created with ``block_trackers=False``, and then names every member of
    Camoufox's own default set rather than one addon, so the setting keeps meaning
    "none of theirs" if that set ever grows; ``firefox_user_prefs`` is sent only in the
    second case, as a fresh copy because Camoufox writes into the mapping it is given.

    Never returns ``viewport`` or ``no_viewport``: Camoufox's ``AsyncNewBrowser``
    defaults a window-spoofing persistent context to ``no_viewport=True`` and only
    when the caller supplied neither key. That default is what keeps Playwright from
    asking Juggler to resize a window Camoufox has pinned, a handshake with no
    timeout (daijro/camoufox#666).
    """
    headless = config.headless if opts.headless is None else opts.headless
    if headless == "virtual" and not IS_LINUX:
        raise ValueError(
            "headless 'virtual' requires Linux (it spawns an Xvfb X server); "
            "use 'true' on this platform"
        )
    if bool(opts.viewport_width) != bool(opts.viewport_height):
        # Camoufox pins a window, not an axis, so half a pair is not a smaller
        # request: it is a request this function cannot honour. Dropping it silently
        # launched a default-sized window and left the caller to discover it.
        raise ValueError(
            "viewport_width and viewport_height must be supplied together; a window size needs both"
        )
    kwargs: dict[str, Any] = {
        "headless": headless,
        "persistent_context": True,
        "user_data_dir": str(user_data_dir),
        "block_images": opts.block_images,
        "block_webrtc": opts.block_webrtc,
        "env": config.launch_env(),
    }
    if config.humanize is not None:
        kwargs["humanize"] = config.humanize
    if config.browser_version:
        kwargs["browser"] = config.browser_version
    if opts.fingerprint_os:
        kwargs["os"] = opts.fingerprint_os
    if opts.locale:
        kwargs["locale"] = opts.locale
    if opts.viewport_width and opts.viewport_height:
        kwargs["window"] = (opts.viewport_width, opts.viewport_height)
    if addon_dirs:
        kwargs["addons"] = addon_dirs
    if not config.bundled_addons or not opts.block_trackers:
        # 2 independent levers, unioned so neither can cancel the other.
        # CAMOUFOX_BUNDLED_ADDONS=false is the server-wide "no extension at all" the
        # marker probes need; block_trackers=False is one session asking for a tracker
        # request to go through. Each is a reason to exclude and neither is ever a
        # reason to keep, so there is no combination in which one undoes the other.
        # Imported here so camoufox stays out of this module's import, as in Session.create.
        from camoufox.addons import DefaultAddons

        kwargs["exclude_addons"] = list(DefaultAddons)
    if not opts.block_trackers:
        # A fresh dict per launch: camoufox writes into the mapping it is handed
        # (`gfx.bundled-fonts.activate`, `permissions.default.image`, the cache prefs),
        # so passing the constant by reference would let one launch's values accumulate
        # in it. Every value here is a scalar, so a shallow copy is the whole isolation.
        kwargs["firefox_user_prefs"] = dict(TRACKER_PREFS_OFF)
    if config.proxy:
        kwargs["proxy"] = config.proxy
    if config.geoip_forced:
        kwargs["geoip"] = True
    if config.camoufox_binary:
        kwargs["executable_path"] = config.camoufox_binary
    return kwargs
