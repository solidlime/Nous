.PHONY: lint test test-all typecheck coverage coverage-fail bandit ci

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

coverage-fail:
	pytest --cov=nous --cov-fail-under=70 --cov-report=term

bandit:
	bandit -r nous/ -ll

ci: lint typecheck test-all bandit coverage-fail
