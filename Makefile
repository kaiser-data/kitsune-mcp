.PHONY: dev test lint format docs build run clean

dev:
	uv sync --extra dev --group docs

test:
	uv run --extra dev pytest tests/ -q

lint:
	uv run --extra dev ruff check .
	uv run --extra dev ruff format --check .

format:
	uv run --extra dev ruff format .

docs:
	uv run --only-group docs mkdocs serve

build:
	uv build

run:
	uv run kitsune-mcp

clean:
	rm -rf dist/ build/ site/ *.egg-info __pycache__ .pytest_cache .ruff_cache .coverage
