# SPEC — チャット LLM: Thinking トグル + ヴァリアント（effort）設定

> 出典: ユーザー要望 (2026-08-08)。調査: exp-1/exp-2（コード構造）、lib-1（ヴァリアント仕様調査）

## 背景

チャット LLM の推論（thinking / reasoning）を WebUI から制御したい。

- **thinking on/off**: トグルで推論モード有効/無効を切替
- **ヴァリアント**: 思考の深さレベル（effort）。ユーザーは「max, high 等の名称は全 LLM 共通か？」と質問

### ヴァリアント仕様調査の結論（lib-1）

- **統一規格は存在しない**。ただし OpenAI 系エコシステム（OpenAI / OpenRouter / xAI / DeepSeek）では
  `reasoning_effort` / `reasoning: {effort}` がデファクトで、値セット `none/minimal/low/medium/high/xhigh/max` がほぼ共有
- Anthropic は **effort 概念なし**（`thinking: {type: "enabled", budget_tokens: 1024〜128000}` のトークン予算方式）
- Gemini 3.x は `thinkingConfig.thinkingLevel`（minimal/low/medium/high）、2.5 は `thinkingBudget`（トークン数）
- OpenRouter の `reasoning` オブジェクト: `{"effort": "low"|"medium"|"high"|"max"|...}`（`supported_efforts` はモデル毎に異なる。非対応値は最寄りにマッピング）

**設計方針**: 設定値は統一の 4 段階 effort（`low` / `medium` / `high` / `max`）+ on/off を保持し、
**プロバイダ実装側で各 API 形式に変換**する。UI はトグル（on/off）+ スライダー（4 段階）。

## 要件

| # | 要件 | 内容 |
|---|------|------|
| R1 | 設定フィールド | `ProviderConfig` に `reasoning_enabled: bool = False` と `reasoning_effort: str = "medium"` を追加（バリデータ付き: 値は `low/medium/high/max` のみ許可） |
| R2 | stream() 拡張 | `LLMProvider.stream()` に `reasoning_effort: str | None = None` を追加（None = オフ）。抽象メソッド + 全実装を更新 |
| R3 | OpenAI/OpenRouter 変換 | `OpenAICompatProvider`: base_url が OpenRouter なら `reasoning: {"effort": X}`、それ以外（OpenAI 等）は `reasoning_effort: X` を kwargs に追加。None なら何も送らない |
| R4 | Anthropic 変換 | `AnthropicProvider`: `thinking: {"type": "enabled", "budget_tokens": N}` に変換。effort→budget マッピング: low=2048 / medium=4096 / high=8192 / max=16384（Anthropic の下限 1024 を満たす） |
| R5 | Gemini | OpenAI 互換エンドポイント経由のため R3 と同じ経路で送信（Gemini 側で非対応なら無視される前提。YAGNI: thinkingLevel 変換は今回スコープ外） |
| R6 | パイプライン伝播 | `inference.py` の `provider.stream()` 呼び出しに `reasoning_effort=config.reasoning_effort if config.reasoning_enabled else None` を渡す |
| R7 | UI: トグル+スライダー | 設定サイドバー「基本設定」に「思考モード（Reasoning）」チェックボックス + effort スライダー（low/medium/high/max の 4 段階、ラベル表示付き）。チェック OFF 時はスライダー disabled |
| R8 | UI: 保存 | `chat-settings.js` の load/apply/save に新 2 フィールドを追加。`GET/POST /api/chat/{persona}/config` はフラットフィールド自動反映（ChatConfig Facade 経由）で追加実装不要 |
| R9 | テスト | (a) ProviderConfig バリデータ（不正値拒否）(b) reasoning_effort が enabled 時に stream へ伝播・無効時 None (c) OpenAICompatProvider の kwargs マッピング（OpenRouter vs OpenAI 形式）(d) Anthropic の thinking 変換 |

### 制約
- 既存呼び出し元（memory_enricher, summarizer 等の 19 箇所）は stream() に reasoning_effort を渡さない → デフォルト None で後方互換維持
- Anthropic の budget_tokens は 1024 未満にしない
- effort 値が非対応モデルに送られた場合の挙動はプロバイダ任せ（最寄りマッピング or 無視）— アプリ側では検証しない
- API キー保護・persona 不変ルールは既存のまま（追加変更なし）

## 検証要件

| # | 項目 | 方法 |
|---|------|------|
| V1 | 単体テスト | 上記 R9 のテストを追加し実行: `pytest tests/unit/test_provider_config.py tests/unit/test_chat_service.py tests/unit/test_chat_pipeline.py tests/unit/test_llm_vision.py`（既存ファイルが無ければ該当テストを追加） |
| V2 | 回帰 | 変更モジュールに直接依存するテストのみ個別実行（フルスイート禁止: メモリ不足のため） |
| V3 | lint | `ruff check` PASS |
| V4 | 型チェック | `py_compile` / mypy 該当範囲 |
| V5 | UI 確認 | ブラウザ実機確認（agent-browser）: 設定パネルにトグル+スライダー表示、OFF 時 disabled、保存→リロードで復元。Docker 再起動手順（MEMORY.md 参照） |

## 実装方針
- バックエンド（provider_config / base / openai_compat / anthropic / inference + テスト）と
  フロントエンド（chat_sidebar_core.py / chat-settings.js）は独立 → **並列 fixer**
- UI は設計子（#057）の介入不要: 既存パターン（動的温度調整チェックボックス + 感情温度スライダー）の踏襲で統一感が保たれる
- ドキュメント: `nous/` 配下コード変更 → docs/README/CLAUDE.md 更新 or `[skip-docs]` 明示。MCP ツール変更なし → llm_usage_guide.md 更新不要
