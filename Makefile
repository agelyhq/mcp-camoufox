.PHONY: install build lint format test run clean

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

run:
	uv run mcp-camoufox

clean:
	rm -rf .venv build dist *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
