.PHONY: lint test test-all contract typecheck coverage coverage-fail bandit ci docs-sync docs-drift search-quality-smoke

lint:
	uv run ruff check . && uv run ruff format --check .

test:
	uv run pytest tests/unit/ -q

test-all:
	uv run pytest -q --ignore=tests/contracts

contract:
	uv run --extra contract pytest tests/contracts/consumer -q

docs-sync:
	@grep -rn "run_tests\.py" AGENTS.md README.md docs/http_api_reference.md docs/architecture.md; test $$? -eq 1

docs-drift:
	uv run python scripts/check_docs_drift.py

search-quality-smoke:
	uv run python scripts/search_quality_smoke.py --out output/search_quality_smoke

typecheck:
	f=$$(mktemp); uv run mypy nous/ > $$f 2>&1; rc=$$?; \
	  if [ $$rc -gt 1 ]; then cat $$f; rm -f $$f; exit 1; fi; \
	  uv run mypy-baseline filter < $$f; r=$$?; rm -f $$f; exit $$r

coverage:
	uv run pytest --cov=nous --cov-report=term --ignore=tests/contracts

coverage-fail:
	uv run pytest --cov=nous --cov-fail-under=70 --cov-report=term --ignore=tests/contracts

bandit:
	uv run bandit -r nous/ -ll

ci: lint typecheck test-all contract bandit coverage-fail docs-sync docs-drift search-quality-smoke
