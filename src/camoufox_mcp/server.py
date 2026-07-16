from __future__ import annotations

import logging
from datetime import UTC, datetime

from camoufox_mcp.bootstrap import build_server
from camoufox_mcp.config import ServerConfig
from camoufox_mcp.daemon.proxy import run_proxy


def _configure_logging(config: ServerConfig) -> None:
    # stdio transport: logs MUST go to a file, never to stdout/stderr. Harden the
    # data root and its credential-bearing subdirs to 0o700 at the same time.
    config.ensure_private_dirs()
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    handler = logging.FileHandler(config.logs_dir / f"server-{stamp}.log", encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[handler],
    )
    # The server_start/session_closed markers now cover the lifecycle events this
    # logger emitted at INFO, so quiet its per-request noise.
    logging.getLogger("mcp.server.lowlevel").setLevel(logging.WARNING)


def main() -> None:
    config = ServerConfig.from_env()
    _configure_logging(config)
    if config.daemon_enabled:
        run_proxy(config)
    else:
        build_server(config).run(transport="stdio")


if __name__ == "__main__":
    main()
