.PHONY: lint test test-all typecheck coverage coverage-fail bandit ci

lint:
	ruff check . && ruff format --check .

test:
	pytest tests/unit/ -q

test-all:
	pytest -q --ignore=tests/contracts

contract:
	pytest tests/contracts/consumer -q

docs-sync:
	! grep -rn "run_tests\.py" CLAUDE.md README.md docs/http_api_reference.md docs/architecture.md

typecheck:
	mypy nous/

coverage:
	pytest --cov=nous --cov-report=term

coverage-fail:
	pytest --cov=nous --cov-fail-under=70 --cov-report=term

bandit:
	bandit -r nous/ -ll

ci: lint typecheck test-all contract bandit coverage-fail docs-sync
