.PHONY: run test lint format

run:
	uv run uvicorn titanai.main:app --reload

test:
	uv run pytest

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/
