.PHONY: install build lint format test test-oldest test-latest run clean

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

# The stack `uv tool install` actually resolves, which is NOT the locked one: uv.lock binds
# only `uv sync`, so a fresh install gets the newest fastmcp/mcp the pyproject bounds allow
# while the lock stays where it was last written. Before fastmcp was bounded `<4`, the 2
# stacks ordered startup differently: fastmcp 4 suspends between our lifespan and the stdio
# read, which is where the 0.4.0 "Connection closed" crash lived, and
# tests/test_stdio_startup.py was red on that stack with the old updater while passing, bug
# present, on the locked one. The bound keeps users on 3.x; this target still proves the
# newest 3.x users actually get (docs/decisions.md names the 6 tests 4 fails). Own
# environment, filled by `uv pip` because that is the one uv path that neither reads nor
# writes uv.lock, then run with --no-sync so uv does not "repair" it back to the lock. Only
# the stdio scenario runs here: it is the test that the locked stack cannot fail.
test-latest:
	uv venv --clear .venv-latest
	uv pip install --python .venv-latest --upgrade -e ".[dev]"
	CAMOUFOX_HEADLESS=true UV_PROJECT_ENVIRONMENT=.venv-latest uv run --no-sync pytest tests/test_stdio_startup.py

run:
	uv run mcp-camoufox

clean:
	rm -rf .venv .venv-build .venv312 .venv-latest build dist *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
