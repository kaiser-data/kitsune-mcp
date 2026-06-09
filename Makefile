.PHONY: install dev test lint format build publish run clean

install:
	uv pip install -e .

dev:
	uv pip install -e ".[dev]"

test:
	uv run --extra dev -m pytest tests/ -v

lint:
	uv run --extra dev -m ruff check server.py server_forge.py kitsune_mcp/ tests/

format:
	uv run --extra dev -m ruff format server.py server_forge.py kitsune_mcp/ tests/

build:
	uv run -m build

publish:
	uv run -m twine upload dist/*

run:
	uv run python server.py

clean:
	rm -rf dist/ build/ *.egg-info __pycache__ .pytest_cache
