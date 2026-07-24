.PHONY: lint test test-all typecheck coverage ci

lint:
	ruff check . && ruff format --check .

test:
	pytest tests/unit/ -q

test-all:
	pytest -q

typecheck:
	mypy nous/

coverage:
	pytest --cov=nous --cov-report=term

ci: lint typecheck test-all coverage
