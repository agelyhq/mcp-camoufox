.PHONY: install build lint format test test-oldest run clean

install:
	uv sync --extra dev

# The runtime dependency set on its own, proving the package installs without anything
# from the dev extra. It gets its OWN environment: `uv sync --no-dev` against the shared
# .venv uninstalls pytest, pytest-timeout, flask and ruff, and `uv run` then silently
# falls through to whatever binary PATH offers — which is how a closing run once
# collected the whole suite under an unrelated interpreter and reported a phantom
# `No module named 'fastmcp.server.providers'`.
build:
	UV_PROJECT_ENVIRONMENT=.venv-build uv sync --no-dev

# Every target below names --extra dev so uv reinstalls it if something removed it,
# instead of running a PATH binary against the wrong site-packages.
lint:
	uv run --extra dev ruff check .
	uv run --extra dev ruff format --check .

format:
	uv run --extra dev ruff format .
	uv run --extra dev ruff check --fix .

test:
	CAMOUFOX_HEADLESS=true uv run --extra dev pytest

# The oldest interpreter requires-python accepts, in its own environment so it never disturbs
# the default one. Worth 1 command because the 2 versions have already differed in a way that
# hid a defect: 3.13's asyncio unlinks a closed Unix socket and 3.12's does not.
test-oldest:
	CAMOUFOX_HEADLESS=true UV_PROJECT_ENVIRONMENT=.venv312 uv run --python 3.12 --extra dev pytest

run:
	uv run mcp-camoufox

clean:
	rm -rf .venv .venv-build .venv312 build dist *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
