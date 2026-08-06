"""``ServerConfig.from_env`` and what the composition root does with what it returns.

Nothing here uses :func:`tests.helpers.isolate_camoufox_env`. That helper substitutes
``"true"`` for an empty ambient ``CAMOUFOX_HEADLESS``, which is the exact input half of
this module is about, so it hid an unstartable server from the whole suite.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import pytest
from fastmcp import Client, Context

from camoufox_mcp.bootstrap import build_server
from camoufox_mcp.config import DEFAULT_ADDON_URLS, DEFAULT_BROWSER_VERSION, ServerConfig
from camoufox_mcp.proxy_url import redact_proxy

if TYPE_CHECKING:
    from fastmcp import FastMCP

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Every variable ``config.py`` reads, taken from the source rather than retyped: the
# equality claims below are only worth something if the list they iterate is complete,
# and a variable added without a line here would otherwise be silently unexamined.
_ENV_VARS = tuple(
    sorted(
        set(
            re.findall(
                r'os\.getenv\(\s*"(CAMOUFOX_[A-Z_]+)"',
                (_REPO_ROOT / "src" / "camoufox_mcp" / "config.py").read_text(encoding="utf-8"),
            )
        )
    )
)

# The 2 variables whose blank value is a documented choice, not an absence:
# ``CAMOUFOX_ADDON_URLS`` blank loads no addons of ours, and ``CAMOUFOX_BROWSER_VERSION``
# blank opts out of the build pin. Both are asserted on their own below.
_BLANK_MEANS_SOMETHING = ("CAMOUFOX_ADDON_URLS", "CAMOUFOX_BROWSER_VERSION")

_BLANK_MEANS_UNSET = tuple(v for v in _ENV_VARS if v not in _BLANK_MEANS_SOMETHING)


def _bare_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete every ``CAMOUFOX_*`` variable, so only what a test sets reaches ``from_env``.

    ``from_env`` creates nothing on disk (the directories are made later, by
    ``ensure_private_dirs``), so leaving ``CAMOUFOX_DATA_DIR`` unset here is safe and
    keeps the baseline config identical to a first-ever run.
    """
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _env_example_assignments() -> dict[str, str]:
    """The uncommented ``KEY=VALUE`` lines of the shipped ``.env.example``."""
    text = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        values[key] = value
    return values


def test_the_env_var_list_is_complete() -> None:
    """Guard on the guard: the scrape must find the variables, not silently nothing."""
    assert len(_ENV_VARS) >= 12, _ENV_VARS
    assert "CAMOUFOX_HEADLESS" in _ENV_VARS
    assert "CAMOUFOX_FINGERPRINT_OS" in _ENV_VARS


@pytest.mark.parametrize("variable", _BLANK_MEANS_UNSET)
def test_a_blank_value_is_exactly_the_same_as_unset(
    variable: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every optional variable but the 2 documented ones treats blank as absent.

    ``CAMOUFOX_HEADLESS`` and ``CAMOUFOX_FINGERPRINT_OS`` used to raise instead, which
    killed the server: ``server.py`` builds the config before it configures logging, so
    the traceback reached stderr only and the client saw a dead process with no reason.
    The comparison is against the whole frozen config, so "does not raise" is not enough:
    blank has to land on the same value the default does.
    """
    _bare_env(monkeypatch)
    default = ServerConfig.from_env()

    monkeypatch.setenv(variable, "")

    assert ServerConfig.from_env() == default


def test_the_shipped_env_example_starts_a_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sourcing ``.env.example`` unedited must produce a usable config.

    It ships as something to copy and edit, under a header calling every variable
    optional, and it carried a blank ``CAMOUFOX_FINGERPRINT_OS`` that raised on read.
    """
    _bare_env(monkeypatch)
    assignments = _env_example_assignments()
    assert "CAMOUFOX_FINGERPRINT_OS" in assignments, "the file no longer assigns the OS"
    for key, value in assignments.items():
        monkeypatch.setenv(key, value)

    config = ServerConfig.from_env()

    assert config.session_defaults.fingerprint_os is None
    # The pin is the one variable the file deliberately leaves commented out, because a
    # blank value would unpin the browser. Sourcing the file must not move the build.
    assert config.browser_version == DEFAULT_BROWSER_VERSION


@pytest.mark.parametrize(
    ("variable", "field", "blank_value", "unset_value"),
    [
        ("CAMOUFOX_ADDON_URLS", "addon_urls", (), DEFAULT_ADDON_URLS),
        ("CAMOUFOX_BROWSER_VERSION", "browser_version", None, DEFAULT_BROWSER_VERSION),
    ],
)
def test_the_2_variables_whose_blank_value_is_a_choice(
    variable: str,
    field: str,
    blank_value: object,
    unset_value: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control for the test above: these 2 are excluded because blank means something.

    Without this, "blank means unset" could be made universal and the exclusions would
    read as an oversight rather than as the documented behaviour they are.
    """
    _bare_env(monkeypatch)
    assert getattr(ServerConfig.from_env(), field) == unset_value

    monkeypatch.setenv(variable, "")

    assert getattr(ServerConfig.from_env(), field) == blank_value


@pytest.mark.parametrize("value", ["1280x0", "0x720", "0x0"])
def test_a_zero_viewport_dimension_is_refused_at_startup(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 0 passes ``isdigit`` and fails every launch afterwards, naming neither variable."""
    _bare_env(monkeypatch)
    monkeypatch.setenv("CAMOUFOX_VIEWPORT", value)

    with pytest.raises(ValueError, match="CAMOUFOX_VIEWPORT"):
        ServerConfig.from_env()


def test_a_usable_viewport_still_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control for the test above: the rejection is of 0, not of viewports."""
    _bare_env(monkeypatch)
    monkeypatch.setenv("CAMOUFOX_VIEWPORT", "1280x720")

    defaults = ServerConfig.from_env().session_defaults

    assert (defaults.viewport_width, defaults.viewport_height) == (1280, 720)


def test_an_ipv6_proxy_keeps_the_brackets_its_authority_needs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``urlparse`` strips the brackets, and the naive rebuild is not an address.

    ``http://::1:3128`` is what we used to hand Playwright, and nothing can read it back
    as a host and a port. The assertion is that round trip, not the literal string.
    """
    _bare_env(monkeypatch)
    monkeypatch.setenv("CAMOUFOX_PROXY", "http://[::1]:3128")

    proxy = ServerConfig.from_env().proxy

    assert proxy == {"server": "http://[::1]:3128"}
    reread = urlparse(proxy["server"])
    assert (reread.hostname, reread.port) == ("::1", 3128)


def test_percent_encoded_proxy_credentials_reach_the_proxy_decoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Percent-encoding is the only way a URL can carry ``@`` or ``:`` in a password.

    Passed through literally, as ``p%40ss``, every request 407s, and there is no other
    spelling available: such a password simply could not be configured.
    """
    _bare_env(monkeypatch)
    monkeypatch.setenv("CAMOUFOX_PROXY", "http://user%40corp:p%40ss%3Aword@proxy.test:8080")

    proxy = ServerConfig.from_env().proxy

    assert proxy == {
        "server": "http://proxy.test:8080",
        "username": "user@corp",
        "password": "p@ss:word",
    }
    # The credentials are the reason a proxy is never logged verbatim.
    assert redact_proxy(proxy) == "http://proxy.test"


def test_a_literal_percent_in_a_proxy_password_is_written_encoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other side of the decode: ``%25`` is how a real ``%`` is spelled.

    This is the compatibility cost of decoding, pinned so it is a decision and not a
    surprise: a password holding ``%`` has to be encoded like the URL grammar always
    required, and in exchange ``@`` and ``:`` become expressible at all.
    """
    _bare_env(monkeypatch)
    monkeypatch.setenv("CAMOUFOX_PROXY", "http://u:100%25sure@proxy.test:8080")

    assert ServerConfig.from_env().proxy == {
        "server": "http://proxy.test:8080",
        "username": "u",
        "password": "100%sure",
    }


@pytest.mark.parametrize("value", ["http://host:abc", "http://host:99999"])
def test_an_unusable_proxy_port_names_the_variable(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``urlparse`` defers the port to a property, so the raise was Python's own.

    "Port could not be cast to integer value as 'abc'" arrives before logging exists and
    is the one proxy error that never named ``CAMOUFOX_PROXY``.
    """
    _bare_env(monkeypatch)
    monkeypatch.setenv("CAMOUFOX_PROXY", value)

    with pytest.raises(ValueError, match="CAMOUFOX_PROXY"):
        ServerConfig.from_env()


def test_a_plain_proxy_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control for the 4 proxy tests above: the ordinary form still parses as before."""
    _bare_env(monkeypatch)
    monkeypatch.setenv("CAMOUFOX_PROXY", "http://user:pass@proxy.test:8080")

    assert ServerConfig.from_env().proxy == {
        "server": "http://proxy.test:8080",
        "username": "user",
        "password": "pass",
    }


def _server_with_probe(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> FastMCP:
    """A real server, plus 1 extra tool reporting what a tool body can see.

    The probe is what any file under ``tools/`` could have written, which is the point:
    the guarantee has to hold against a tool, not against the composition root's
    intentions.
    """
    _bare_env(monkeypatch)
    monkeypatch.setenv("CAMOUFOX_AUTO_UPDATE", "false")
    monkeypatch.setenv("CAMOUFOX_DATA_DIR", str(data_dir))
    mcp = build_server(ServerConfig.from_env())

    @mcp.tool
    def lifespan_keys(ctx: Context) -> str:
        return ",".join(sorted(ctx.lifespan_context))

    return mcp


async def test_the_lifespan_hands_a_tool_no_way_to_the_session_manager(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path
) -> None:
    """The lifespan must publish nothing: ``ToolDeps`` is the only route to the manager.

    ``Context.lifespan_context`` is public FastMCP surface, and the composition root used
    to yield config, sessions and telemetry into it while nothing read them, so it was the
    last path by which a tool could reach the ``SessionManager`` outside the injected
    ``ToolDeps`` that CLAUDE.md mandates.

    Teeth: an empty answer would also be what a lifespan that never ran returns, so the
    ``server_start`` record is asserted first. That marker is written by the lifespan body,
    2 lines above the yield.
    """
    mcp = _server_with_probe(monkeypatch, data_dir)

    async with Client(mcp) as client:
        server_log = data_dir / "logs" / "_server.jsonl"
        assert "server_start" in server_log.read_text(encoding="utf-8"), (
            "the lifespan body did not run, so an empty context proves nothing"
        )

        assert (await client.call_tool("lifespan_keys", {})).data == ""
