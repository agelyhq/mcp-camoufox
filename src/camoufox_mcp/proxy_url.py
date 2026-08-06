"""Both directions of the ``CAMOUFOX_PROXY`` URL: the parse, and the redaction.

Playwright wants the credentials out of the URL and in their own keys, so the string
has to be taken apart and put back together twice: once into the launch option, once
into the ``server_start`` telemetry record. Keeping both here means the authority form
(brackets, port) is reasoned about once instead of in ``config.py`` and ``bootstrap.py``
separately.
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse


def parse_proxy(raw: str | None) -> dict[str, str] | None:
    """Parse ``CAMOUFOX_PROXY`` into a Playwright proxy dict, or ``None`` when unset.

    The authority is rebuilt with the brackets an IPv6 literal needs put back, because
    ``urlparse`` strips them from ``hostname``: ``http://[::1]:3128`` reassembled naively
    is ``http://::1:3128``, which nothing downstream can read back as an address.

    Credentials are percent-decoded. Percent-encoding is the only way a URL can carry a
    password containing ``@`` or ``:``, so without this those passwords cannot be
    configured at all: the literal ``%40`` reached the proxy and every request got a 407.
    The cost is that a password holding a real ``%`` must now be written ``%25``, which is
    what the URL grammar required of it in the first place.
    """
    if not raw:
        return None
    parsed = urlparse(raw)
    try:
        port = parsed.port
    except ValueError as exc:
        # urlparse defers this to the property, so the raise lands at startup, before
        # logging is configured, as Python's own "Port could not be cast to integer"
        # without ever naming the variable that carried it.
        raise ValueError(f"Invalid CAMOUFOX_PROXY={raw!r}: {exc}") from exc
    if not parsed.hostname:
        raise ValueError(f"Invalid CAMOUFOX_PROXY: {raw!r}")
    proxy: dict[str, str] = {
        "server": f"{parsed.scheme or 'http'}://{authority(parsed.hostname, port)}"
    }
    if parsed.username:
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    return proxy


def redact_proxy(proxy: dict[str, str] | None) -> str | None:
    """Reduce a parsed proxy to ``scheme://host``: never log credentials or port."""
    if not proxy:
        return None
    parsed = urlparse(proxy.get("server", ""))
    if not parsed.hostname:
        return "REDACTED"
    return f"{parsed.scheme or 'http'}://{authority(parsed.hostname, None)}"


def authority(hostname: str, port: int | None) -> str:
    """The URL authority for ``hostname``, bracketed when it is an IPv6 literal."""
    host = f"[{hostname}]" if ":" in hostname else hostname
    return f"{host}:{port}" if port is not None else host
