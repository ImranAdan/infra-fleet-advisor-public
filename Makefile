.PHONY: setup test lint typecheck check

setup:
	uv sync

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy src

check: lint typecheck test
