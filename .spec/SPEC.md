# SPEC — Phase 4: 発展

## 出典
`refactor-instructions.md` 第3章、第5章、第6章

---

## SPEC-4.1: ChatConfig 分割 (refactor 3.3)
**現状**: `nous/domain/chat_config.py` (602行) に50+フィールドのPydanticモデル。SQLシリアライズも内包。

| 新ファイル | 内容 | 想定行数 |
|-----------|------|:--:|
| `provider_config.py` | LLM接続設定 (api_key, base_url, model等) | ~100 |
| `session_config.py` | セッション管理設定 (max_turns, ttl等) | ~100 |
| `compression_config.py` | コンテキスト圧縮設定 | ~80 |
| `tool_config.py` | MCPツール設定 | ~80 |
| `chat_config.py` | Facade: 全設定を集約するPydanticモデル | ~200 |

**要件**: ChatConfig クラスは引き続き1つのPydanticモデルとして動作。内部で設定ブロックに分割。

---

## SPEC-4.2: MCPツール契約テスト導入 (refactor 6.3)
**現状**: MCPツールの入出力が暗黙的。破壊的変更の検出機構なし。

| 項目 | 内容 |
|------|------|
| 対象ツール | memory_create, memory_read, memory_search, memory_update, memory_delete, goal_manage, update_context 等 |
| 方式 | Pact (pact-python) で consumer-driven 契約テスト |
| カバレッジ | 全MCPツールの入出力スキーマ、エラーレスポンス形式 |
| ファイル | `tests/contracts/` ディレクトリ新設 |

**参考**: `~/.agents/skills/contract-testing/SKILL.md` に Pact ワークフローあり。

---

## SPEC-4.3: カバレッジ下限 CI 強制 (refactor 5.2)
**対象**: `.github/workflows/ci.yml`
- `pytest --cov=nous --cov-fail-under=70` をCIに追加
- カバレッジレポートをGitHub Actions artifact に保存

---

## SPEC-4.4: bandit セキュリティ lint (refactor 5.2)
**対象**: `.github/workflows/ci.yml`
- `bandit -r nous/ -ll` をCIジョブとして追加
- `# nosec` 抑制の正当性確認（既にコメント付きなので概ねパスするはず）

---

## 実装方針
- 4.1 (ChatConfig分割) は #011 — 独立した単一ファイル変更
- 4.2 (契約テスト) は #042 (librarian) でPact実装パターン調査 → #011 実装
- 4.3 + 4.4 (CI改善) は直接編集（YAML変更のみ、リスク低）

## 検証要件
| # | 項目 | 方法 |
|---|------|------|
| V1 | ChatConfig import | `from nous.domain.chat_config import ChatConfig` |
| V2 | 既存テスト | `pytest tests/unit/test_chat_config.py` |
| V3 | 契約テスト | `pytest tests/contracts/` |
| V4 | CI | GitHub Actions で bandit + coverage ジョブが動作すること |
