.PHONY: install build lint format test test-oldest run clean

install:
	uv sync --extra dev

build:
	uv sync --no-dev

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

test:
	CAMOUFOX_HEADLESS=true uv run pytest

# The oldest interpreter requires-python accepts, in its own environment so it never disturbs
# the default one. Worth 1 command because the 2 versions have already differed in a way that
# hid a defect: 3.13's asyncio unlinks a closed Unix socket and 3.12's does not.
test-oldest:
	CAMOUFOX_HEADLESS=true UV_PROJECT_ENVIRONMENT=.venv312 uv run --python 3.12 pytest

run:
	uv run mcp-camoufox

clean:
	rm -rf .venv build dist *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
