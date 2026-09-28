"""実機 nous 検索品質のライブ評価テスト。

環境変数 NOUS_EVAL_BASE_URL と NOUS_EVAL_CORPUS が両方設定されている時のみ実行し、
それ以外は skip する。計測ロジックは scripts/eval_search_quality.py を import して
再利用する（重複実装しない）。

閾値はモジュール定数として定義し、環境変数で上書きできる。
デフォルトは暫定で緩め・後で引き上げ予定。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "eval_search_quality.py"
DEFAULT_QUERIES = Path(__file__).resolve().parent / "data" / "search_quality_queries_v1.json"

# --- 暫定閾値（後で引き上げ予定） -------------------------------------------
# 実機ベースラインが安定したら実測に合わせて厳しくする。
DEFAULT_MIN_RECALL5 = 0.5
DEFAULT_MIN_MRR = 0.5
DEFAULT_MAX_ZERO_RESULTS = 0
DEFAULT_LIMIT = 20
DEFAULT_TIMEOUT = 30
# ---------------------------------------------------------------------------


def _load_eval_module():
    """scripts/eval_search_quality.py をパス指定で import する。"""
    if not SCRIPT_PATH.exists():
        pytest.skip(f"eval harness script not found: {SCRIPT_PATH}")
    spec = importlib.util.spec_from_file_location("eval_search_quality", SCRIPT_PATH)
    assert spec and spec.loader, f"cannot load eval module from {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["eval_search_quality"] = module
    spec.loader.exec_module(module)
    return module


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@pytest.fixture(scope="module")
def eval_result() -> dict:
    base_url = os.environ.get("NOUS_EVAL_BASE_URL")
    corpus = os.environ.get("NOUS_EVAL_CORPUS")
    if not base_url:
        pytest.skip("NOUS_EVAL_BASE_URL not set")
    if not corpus:
        pytest.skip("NOUS_EVAL_CORPUS not set")

    queries = os.environ.get("NOUS_EVAL_QUERIES", str(DEFAULT_QUERIES))
    persona = os.environ.get("NOUS_EVAL_PERSONA", "herta")
    limit = _env_int("NOUS_EVAL_LIMIT", DEFAULT_LIMIT)
    timeout = _env_int("NOUS_EVAL_TIMEOUT", DEFAULT_TIMEOUT)

    module = _load_eval_module()
    return module.run_eval(base_url, persona, queries, corpus, limit, timeout)


def test_recall_at_5(eval_result: dict) -> None:
    threshold = _env_float("NOUS_EVAL_MIN_RECALL5", DEFAULT_MIN_RECALL5)
    actual = eval_result["summary"].get("recall@5_mean", 0.0)
    assert actual >= threshold, f"recall@5 mean {actual:.4f} < threshold {threshold}"


def test_mrr(eval_result: dict) -> None:
    threshold = _env_float("NOUS_EVAL_MIN_MRR", DEFAULT_MIN_MRR)
    actual = eval_result["summary"].get("mrr_mean", 0.0)
    assert actual >= threshold, f"MRR mean {actual:.4f} < threshold {threshold}"


def test_no_zero_results(eval_result: dict) -> None:
    threshold = _env_int("NOUS_EVAL_MAX_ZERO_RESULTS", DEFAULT_MAX_ZERO_RESULTS)
    summary = eval_result["summary"]
    assert summary["zero_result_count"] <= threshold, (
        f"zero-result {summary['zero_result_count']} > {threshold}: {summary['zero_result_ids']}"
    )


def test_no_query_errors(eval_result: dict) -> None:
    errors = [m for m in eval_result["rows"] if "error" in m]
    assert not errors, f"queries failed: {[m['id'] for m in errors]}"
