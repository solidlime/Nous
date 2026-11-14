# 設計: プロバイダー UI の base_url 必須化 ＋ OpenAI互換統一 ＋ reasoning トグル修正

日付: 2026-08-29
ステータス: 承認済み（ユーザー確認 2026-08-29）

## 背景と課題

1. **UI**: WebUI のチャット設定でプロバイダーをドロップダウン（anthropic/openai/openrouter/google/opencode_go）から選ぶ方式。ユーザーはドロップダウンを廃止し、base_url 入力を必須にしたい。
2. **バグ**: `https://api.commandcode.ai/provider/v1` + `deepseek/deepseek-v4-flash-vision-exp` で Reasoning ON でも `reasoning_content` が返らない。原因（@librarian 調査確定）: DeepSeek V4 は hybrid モデルで `reasoning_effort` だけでは thinking が有効化されない。公式仕様では別途トグル（`thinking: {"type": "enabled"}`）が必要。OpenAI互換サーバーは未知パラメータを黙って無視するため、エラーも出ずに reasoning_content が返らないだけ。

## 決定事項（ユーザー承認済み）

- **常に OpenAI互換**: 全接続を `OpenAICompatProvider` に統一。Anthropic 純正 SDK 経路は使わない（Claude は `https://api.anthropic.com/v1/` 互換レイヤー経由）。
- **UI**: プロバイダードロップダウン廃止、base_url 常時表示＋必須。
- **reasoning**: `reasoning_effort` 維持 ＋ `extra_body` で両トグル（`thinking` / `enable_thinking`）併送。

## 変更内容

### ① UI（`nous/api/http/sections/chat/chat_sidebar_core.py` + `nous/api/http/static/chat/chat-settings.js`）

- `chat_sidebar_core.py` L25-34: 「プロバイダー」`<select id="chat-provider">` ブロック削除。
- L43-46: base_url 行を常時表示化。ラベルを「Base URL（必須）」に変更、placeholder を `https://api.commandcode.ai/provider/v1` 等に更新。
- `chat-settings.js`:
  - `onChatProviderChange()`（L347-354）削除。
  - `loadChatConfig` 内 `set("chat-provider", ...)` 削除（L39）。
  - `saveChatConfig` の payload から `provider` キー削除（L365）。
  - `saveChatConfig` 冒頭に base_url 空チェック追加 → `toast("Base URL は必須です", "error")` で中断。
- **サーバー側必須バリデーションは行わない**: ProviderConfig に必須制約を入れると旧 config.json の読み込みが ValidationError → デフォルト fallback で既存設定が消える。クライアント側のみでガード。

### ② バックエンド（`nous/infrastructure/llm/factory.py` + `nous/domain/provider_config.py`）

- `factory.py`:
  - `get_provider()` を常に `OpenAICompatProvider(api_key, model, resolved_base_url)` を返すよう変更。
  - 旧 provider 名は base_url デフォルト解決のみに使用（移行マップ）:
    - `anthropic` → `https://api.anthropic.com/v1/`
    - `google` → `https://generativelanguage.googleapis.com/v1beta/openai/`
    - `openai` → `https://api.openai.com/v1`
    - `openrouter` → `https://openrouter.ai/api/v1`
    - `opencode_go` → `https://opencode.ai/zen/go/v1`
    - 未知/空 → デフォルトなし（base_url 必須運用）
- `provider_config.py`: `provider` フィールドは schema 互換のため残置するが動作には使わない（`_DEFAULT_MODELS` は残す＝モデル空時のフォールバックに使用中）。
- `anthropic.py` / `google.py` は削除せず温存（単体テストが参照中。削除は別タスク）。

### ③ reasoning トグル修正（`nous/infrastructure/llm/openai_compat.py`）

L155-161 現行:

```python
if reasoning_effort:
    if "openrouter" in (self.base_url or "").lower():
        kwargs["reasoning"] = {"effort": reasoning_effort}
    else:
        kwargs["reasoning_effort"] = reasoning_effort
```

変更後:

```python
if reasoning_effort:
    # Hybrid reasoning モデル（DeepSeek V4 等）は effort だけでは thinking が
    # 有効化されない。トグルを併送する（未知キーは OpenAI互換サーバーで無視される）。
    kwargs["reasoning_effort"] = reasoning_effort
    kwargs["extra_body"] = {
        "thinking": {"type": "enabled"},   # DeepSeek 公式仕様
        "enable_thinking": True,           # vLLM / Alibaba 系
    }
```

- OpenRouter 分岐の `reasoning: {"effort": ...}` は削除（OpenRouter は `reasoning_effort` も受理する。@librarian 調査出典: OpenRouter API docs）。OpenRouter に対して extra_body の `thinking` / `enable_thinking` は未知キーなので無視される。
- temperature/top_p 抑制（推論モデルは sampling params 送信不可）は現行維持。

### ④ 検証

- **単体**:
  - `tests/unit/test_llm_reasoning.py`（既存）に extra_body アサーション追加: reasoning 有効時に kwargs に `reasoning_effort` と `extra_body.thinking.type == "enabled"` / `extra_body.enable_thinking is True` があること。
  - factory のテスト: 旧 provider 名が正しいデフォルト base_url で OpenAICompatProvider を返すこと、未知 provider がエラーではなく base_url 空で返ること。
  - UI 保存フローの単体は JS なので実機確認で代替。
- **実機**: ユーザーの commandcode.ai キーで curl 4 パターン（effort のみ / +thinking / +enable_thinking / 両方）を `stream: true` で叩き、`delta.reasoning_content` 出現を確認。有効だったパターンが実装と一致すること。
- **UI 実ブラウザ確認**: base_url 必須バリデーション（空で保存→toast）、旧 config（provider 残存・base_url 空）での起動挙動、チャット1ターン。

## 非目標（スキップ）

- `reasoning_param_style` のような新設定フィールド（過剰設計）
- サーバー側 base_url 必須バリデーション（旧 config 破壊リスク）
- `anthropic.py` / `google.py` の削除
- GeminiProvider の openai_compat 移行検証（google は互換 URL を使うが詳細検証は別途）

## 影響範囲

- `nous/api/http/sections/chat/chat_sidebar_core.py`
- `nous/api/http/static/chat/chat-settings.js`
- `nous/infrastructure/llm/factory.py`
- `nous/infrastructure/llm/openai_compat.py`
- `nous/domain/provider_config.py`（provider フィールドのコメント明記のみ、実質変更なし）
- `tests/unit/test_llm_reasoning.py`、factory テスト（新規または `tests/unit/` 既存ファイル追記）
