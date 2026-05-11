.PHONY: help install check test lint format types mock-check serve docker clean

help:
	@echo "Targets:"
	@echo "  install     - sync dependencies via uv"
	@echo "  check       - run all checks: format + lint + types + tests + mock-check"
	@echo "  test        - run pytest"
	@echo "  lint        - ruff check"
	@echo "  format      - ruff format"
	@echo "  types       - mypy --strict"
	@echo "  mock-check  - check for synthetic data in non-test code"
	@echo "  serve       - local uvicorn server on port 8765"
	@echo "  docker      - build the Railway-ready image"
	@echo "  clean       - remove caches"

install:
	uv sync --all-extras
	uv run pre-commit install

check: format lint types mock-check test
	@echo "✓ all checks passed"

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

types:
	uv run mypy tijuana_dispersion --strict

mock-check:
	uv run python scripts/check_no_mock_data.py tijuana_dispersion

serve:
	uv run uvicorn tijuana_dispersion.api:app --reload --port 8765

docker:
	docker build -t tijuana-dispersion:dev .

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} +
