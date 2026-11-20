"""#130 再発ガード: integration テストでの Settings() 直構築禁止。

`Settings()` の引数ゼロ直呼びは本番ルートの `get_settings()` キャッシュと
食い違い、full suite 実行時のみ落ちる順序依存 flaky を生む（#130）。
引数付き構築（test_cors.py 等の明示的ユニットテスト）は対象外。
"""

import ast
from pathlib import Path

INTEGRATION_DIR = Path(__file__).resolve().parents[1] / "integration"


def test_integration_tests_never_construct_settings_directly() -> None:
    for path in INTEGRATION_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and not node.args
                and isinstance(node.func, ast.Name)
                and node.func.id == "Settings"
            ):
                raise AssertionError(
                    f"{path.relative_to(INTEGRATION_DIR)}:{node.lineno}: "
                    "Settings() 直構築は get_settings() キャッシュと食い違う (#130)。get_settings() を使うこと。"
                )
