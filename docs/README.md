# docs 索引

ここは **生きた文書（live）** の置き場。live な文書は実装と同期させる義務がある。
実装と食い違ったら、文書側を直す（`scripts/check_docs_drift.py` が CI で検出する）。

## live / frozen

| 区分 | 場所 | 扱い |
|------|------|------|
| live | リポジトリ直下の `README.md` と `docs/` 配下の `*.md`（`archive/` `releases/` `evidence/` を除く） | 実装と同期させる。コード参照（`` `path:line` ``）のドリフトは CI が落とす |
| frozen | `docs/archive/` | 日付時点の記録。**更新しない**。コード参照が古くても直さない（ただし移動に伴うリンク切れの追従のみ行う） |
| frozen | `docs/releases/` | リリース時点のスナップショット |
| frozen | `docs/evidence/` | 画像等の証跡 |

新しい調査・計画・レビューは `docs/archive/<種別>/` に日付付きで置く（`docs/` 直下に増やさない）。

## live 文書

| ファイル | 内容 |
|----------|------|
| [README.md](../README.md) | プロジェクト全体の概要・セットアップ |
| [README.md](./README.md) | この索引（live / frozen の区分と一覧） |
| [architecture.md](architecture.md) | コンポーネント構成、MCP ツール一覧、設定 env |
| [http_api_reference.md](http_api_reference.md) | HTTP API のエンドポイントリファレンス |
| [memory_features.md](memory_features.md) | 記憶機能（忘却曲線・検索・エンリッチメント） |
| [llm_usage_guide.md](llm_usage_guide.md) | LLM 側からの使い方ガイド |
| [backup_restore.md](backup_restore.md) | SQLite・wiki・Qdrant のバックアップ / リストア |
| [sandbox.md](sandbox.md) | コード実行サンドボックスの設定と構成 |
| [claude_desktop_setup.md](claude_desktop_setup.md) | Claude Desktop への接続手順 |
| [decisions/ADR-001-centralized-language-config.md](decisions/ADR-001-centralized-language-config.md) | ADR-001: 中央言語設定の導入 |
| [decisions/ADR-001-appendix-language-resolver-design.md](decisions/ADR-001-appendix-language-resolver-design.md) | ADR-001 補遺: LanguageResolver の設計詳細 |
| [decisions/ADR-002-tts-style-annotation.md](decisions/ADR-002-tts-style-annotation.md) | ADR-002: TTS スタイルアノテーション |
| [decisions/ADR-003-recency-tiebreak-ranking.md](decisions/ADR-003-recency-tiebreak-ranking.md) | ADR-003: recency/importance の相対（乗数）方式 |
