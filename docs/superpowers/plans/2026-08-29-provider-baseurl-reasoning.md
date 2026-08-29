# Provider base_url 必須化＋OpenAI互換統一＋reasoning トグル修正 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WebUI からプロバイダー選択を廃止して base_url 必須運用に移行し、全 LLM 接続を OpenAICompatProvider に統一。さらに reasoning 有効時に DeepSeek 系 hybrid モデルが推論しないバグを `extra_body` トグル併送で修正する。

**Architecture:** `factory.get_provider()` はシグネチャ互換のまま常に `OpenAICompatProvider` を返す（旧 provider 名は base_url デフォルト解決専用の移行マップに降格）。`openai_compat.py` は reasoning 指定時に `reasoning_effort` ＋ `extra_body` トグルを併送。UI はドロップダウン削除＋クライアント側必須バリデーション（サーバー側は既存 config 破壊リスクのため不採用 — `_do_save_chat_config` は body 内のフィールドのみマージするので payload から `provider` を落としても既存値は保持される）。

**Tech Stack:** Python 3.12 / Pydantic / openai SDK (AsyncOpenAI) / vanilla JS / pytest-asyncio

**設計ドキュメント:** `docs/superpowers/specs/2026-08-29-provider-baseurl-reasoning-design.md`（87da0b3c）

## Global Constraints

- pytest 実行は **`python -X utf8 -m pytest`**（Windows/PowerShell、UTF-8 強制）
- `nous/infrastructure/llm/anthropic.py` と `google.py` は**削除しない**（`test_llm_reasoning.py` / `test_llm_vision.py` が参照中）
- `ProviderConfig.provider` フィールドは schema 互換のため残置（env フォールバック `get_effective_api_key` / モデルデフォルト `_DEFAULT_MODELS` は provider 名を使い続ける）
- `get_provider` のシグネチャ `(provider, api_key, model, base_url="")` は**変更禁止**（18 call sites）
- `image_caption_provider`（chat-settings.js L526）は**変更対象外**
- `git push --force` / `git commit --no-verify` 禁止
- コミットメッセージは conventional commits（`feat:` / `test:` / `refactor:`）

---

### Task 1: reasoning トグル併送（openai_compat.py）

**Files:**
- Modify: `nous/infrastructure/llm/openai_compat.py:155-161`
- Test: `tests/unit/test_llm_reasoning.py`（`TestOpenAICompatReasoning` クラス内）

**Interfaces:**
- Consumes: `OpenAICompatProvider.stream(messages, system, tools, temperature, max_tokens, top_p, reasoning_effort)`（既存シグネチャ、変更なし）
- Produces: reasoning 指定時の `create()` kwargs に `reasoning_effort: str` と `extra_body: {"thinking": {"type": "enabled"}, "enable_thinking": True}` が含まれる。OpenRouter 専用分岐 `kwargs["reasoning"]` は削除される。

- [ ] **Step 1: 既存テストを削除・新テストを書く（失敗する状態）**

`tests/unit/test_llm_reasoning.py` の `TestOpenAICompatReasoning` クラス内:

**削除**: `test_openrouter_uses_reasoning_object`（L65-72、OpenRouter 分岐廃止により無効）

**変更**: `test_openai_uses_reasoning_effort`（L75-82）を以下に差し替え:

```python
    @pytest.mark.asyncio
    async def test_reasoning_sends_effort_and_extra_body(self):
        """reasoning 指定 → reasoning_effort + extra_body トグル併送 (DeepSeek V4 / vLLM 対応)."""
        provider = self._make_provider(base_url="https://api.commandcode.ai/provider/v1")
        async for _ in provider.stream(messages=[], system="", reasoning_effort="high"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["reasoning_effort"] == "high"
        assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}, "enable_thinking": True}
```

**変更**: `test_none_adds_nothing`（L85-92）— OpenRouter URL のまま効くが、assert に extra_body を追加:

```python
    @pytest.mark.asyncio
    async def test_none_adds_nothing(self):
        """reasoning_effort=None → effort も extra_body も入らない."""
        provider = self._make_provider(base_url="https://openrouter.ai/api/v1")
        async for _ in provider.stream(messages=[], system="", reasoning_effort=None):
            pass
        kwargs = self._capture_kwargs(provider)
        assert "reasoning" not in kwargs
        assert "reasoning_effort" not in kwargs
        assert "extra_body" not in kwargs
```

**追加**（クラス内末尾に）:

```python
    @pytest.mark.asyncio
    async def test_reasoning_effort_still_sent_for_openrouter(self):
        """OpenRouter も reasoning_effort を受理する → 専用 reasoning オブジェクト分岐は廃止."""
        provider = self._make_provider(base_url="https://openrouter.ai/api/v1")
        async for _ in provider.stream(messages=[], system="", reasoning_effort="low"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["reasoning_effort"] == "low"
        assert "reasoning" not in kwargs
        assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}, "enable_thinking": True}
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -X utf8 -m pytest tests/unit/test_llm_reasoning.py::TestOpenAICompatReasoning -v`
Expected: FAIL（`extra_body` が kwargs に無い KeyError / assert 失敗）— 削除した `test_openrouter_uses_reasoning_object` は消えていること

- [ ] **Step 3: openai_compat.py の実装**

`nous/infrastructure/llm/openai_compat.py` L155-161 を以下に置換:

```python
            if reasoning_effort:
                # 推論モデル (o1/o3/o4-mini 等) は temperature を許可しない (400 Unsupported parameter)。
                # reasoning 指定時は sampling params (temperature/top_p) を送らない
                kwargs["reasoning_effort"] = reasoning_effort
                # ponytail: hybrid reasoning モデル (DeepSeek V4 等) は effort だけでは thinking が
                # 有効化されない。OpenAI互換サーバーは未知キーを黙って無視するため、両トグルを併送
                # (DeepSeek 公式: thinking, vLLM/Alibaba 系: enable_thinking)。
                # 対応表方式 (reasoning_param_style フィールド) は過剰設計のため不採用。
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}, "enable_thinking": True}
                # TODO: 推論モデルは max_tokens ではなく max_completion_tokens が必要。
                # モデル名検出が必要で侵襲が大きいため次回候補（未実施）
            else:
```

（`else:` 以降 L164-167 の temperature/top_p ブロックは現行維持。else のインデント整合に注意）

- [ ] **Step 4: テストが通ることを確認**

Run: `python -X utf8 -m pytest tests/unit/test_llm_reasoning.py -v`
Expected: PASS 27件（28 - 1削除 + 1追加 = 28件）

- [ ] **Step 5: Commit**

```bash
git add nous/infrastructure/llm/openai_compat.py tests/unit/test_llm_reasoning.py
git commit -m "fix(llm): reasoning 有効時 extra_body で thinking/enable_thinking トグルを併送"
```

---

### Task 2: factory の OpenAICompat 統一（factory.py）

**Files:**
- Modify: `nous/infrastructure/llm/factory.py`（全52行を実質書き換え）
- Create: `tests/unit/test_llm_factory.py`

**Interfaces:**
- Consumes: `OpenAICompatProvider(api_key, model, base_url)`（`nous/infrastructure/llm/openai_compat.py:62`、base_url=None の場合は `_OPENAI_BASE_URL` フォールバック）
- Produces: `get_provider(provider: str, api_key: str, model: str, base_url: str = "") -> OpenAICompatProvider`。常に OpenAICompatProvider を返す。旧 provider 名 → base_url デフォルト解決マップ: `anthropic`→`https://api.anthropic.com/v1/`、`google`→`https://generativelanguage.googleapis.com/v1beta/openai/`、`openai`→`https://api.openai.com/v1`、`openrouter`→`https://openrouter.ai/api/v1`、`opencode_go`→`https://opencode.ai/zen/go/v1`、未知/空→`""`（AsyncOpenAI が api.openai.com にフォールバック）。明示 `base_url` 引数があれば最優先。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_llm_factory.py` を新規作成:

```python
"""Tests for LLM factory: 全 provider 名を OpenAICompatProvider に統一."""

from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.llm.openai_compat import OpenAICompatProvider


class TestFactoryUnifiedOpenAICompat:
    def test_anthropic_maps_to_compat_base_url(self):
        """旧 provider=anthropic → OpenAI互換エンドポイント経由の Claude."""
        p = get_provider("anthropic", api_key="k", model="claude-opus-4-5")
        assert isinstance(p, OpenAICompatProvider)
        assert p.base_url == "https://api.anthropic.com/v1/"

    def test_google_maps_to_gemini_compat_base_url(self):
        p = get_provider("google", api_key="k", model="gemini-2.5-flash")
        assert isinstance(p, OpenAICompatProvider)
        assert p.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"

    def test_openrouter_default(self):
        p = get_provider("openrouter", api_key="k", model="m")
        assert isinstance(p, OpenAICompatProvider)
        assert p.base_url == "https://openrouter.ai/api/v1"

    def test_openai_default(self):
        p = get_provider("openai", api_key="k", model="gpt-4o")
        assert isinstance(p, OpenAICompatProvider)
        assert p.base_url == "https://api.openai.com/v1"

    def test_opencode_go_default(self):
        p = get_provider("opencode_go", api_key="k", model="deepseek-v4-pro")
        assert isinstance(p, OpenAICompatProvider)
        assert p.base_url == "https://opencode.ai/zen/go/v1"

    def test_unknown_provider_falls_back_to_openai(self):
        """未知 provider → エラーにせず OpenAI デフォルトで動作継続."""
        p = get_provider("unknown_provider", api_key="k", model="m")
        assert isinstance(p, OpenAICompatProvider)
        assert p.base_url == "https://api.openai.com/v1"

    def test_explicit_base_url_wins(self):
        """明示 base_url は移行マップより優先."""
        p = get_provider("anthropic", api_key="k", model="m", base_url="https://api.commandcode.ai/provider/v1")
        assert p.base_url == "https://api.commandcode.ai/provider/v1"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -X utf8 -m pytest tests/unit/test_llm_factory.py -v`
Expected: FAIL（現行実装は anthropic で AnthropicProvider を返すため isinstance 失敗）

- [ ] **Step 3: factory.py を書き換え**

`nous/infrastructure/llm/factory.py` を全差し替え:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .openai_compat import OpenAICompatProvider

# 旧 provider 名 → OpenAI互換デフォルト base_url（移行マップ）。
# provider 選択は廃止済み。全接続は OpenAICompatProvider に統一され、
# このマップは旧 config.json の provider フィールドから base_url を復元するためにのみ使う。
_DEFAULT_BASE_URLS: dict[str, str] = {
    "anthropic": "https://api.anthropic.com/v1/",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "opencode_go": "https://opencode.ai/zen/go/v1",
}


def get_provider(provider: str, api_key: str, model: str, base_url: str = "") -> "OpenAICompatProvider":
    """常に OpenAICompatProvider を返す（シグネチャ互換維持・18 call sites）。

    base_url が空の場合、旧 provider 名に応じた互換エンドポイントをデフォルト解決する。
    """
    from .openai_compat import OpenAICompatProvider

    resolved_base_url = base_url or _DEFAULT_BASE_URLS.get(provider, "")
    return OpenAICompatProvider(api_key=api_key, model=model, base_url=resolved_base_url)
```

注: 旧実装の `_PROVIDER_REGISTRY` / AnthropicProvider / GeminiProvider 分岐は削除。`base_url=""` + 未知 provider の場合、`OpenAICompatProvider.__init__` の `base_url or _OPENAI_BASE_URL` が api.openai.com にフォールバックする（openai_compat.py:69）。

- [ ] **Step 4: テストが通ること＋既存スイートへの影響確認**

Run: `python -X utf8 -m pytest tests/unit/test_llm_factory.py tests/unit/test_llm_reasoning.py tests/unit/test_llm_vision.py tests/unit/test_image_caption.py -q`
Expected: PASS（test_llm_vision.py / test_image_caption.py は provider クラス直参照のため影響なし）

- [ ] **Step 5: Commit**

```bash
git add nous/infrastructure/llm/factory.py tests/unit/test_llm_factory.py
git commit -m "refactor(llm): factory を OpenAICompatProvider 統一に変更（旧 provider 名は base_url 移行マップに降格）"
```

---

### Task 3: UI — ドロップダウン廃止＋base_url 必須

**Files:**
- Modify: `nous/api/http/sections/chat/chat_sidebar_core.py:25-46`
- Modify: `nous/api/http/static/chat/chat-settings.js`（L39, L100, L347-354, L365, L588）

**Interfaces:**
- Consumes: なし（純粋な UI 削除＋バリデーション追加）
- Produces: `N.Chat.settings.onProviderChange` が名前空間から**削除される**。保存 payload から `provider` キー削除（サーバー `_do_save_chat_config` は body 内フィールドのみマージするため既存 `provider` 値は保持される — chat_management.py:40-44）。

- [ ] **Step 1: chat_sidebar_core.py — プロバイダー select 削除＋base_url 行の常時表示化**

L25-34 の `<div>`（プロバイダー select ブロック）を**丸ごと削除**。L43-46 の base_url 行を以下に差し替え:

```html
                                <div>
                                    <div class="chat-field-label">Base URL <span style="color:var(--accent-blue);font-size:0.7rem;">（必須）</span></div>
                                    <input type="text" id="chat-base-url" class="chat-field-input" placeholder="https://api.commandcode.ai/provider/v1" />
                                </div>
```

注: `id="chat-base-url-row"` と `id="chat-provider"` は参照が全部消えるため撤去。モデル input の placeholder（L37 `例: claude-opus-4-5`）→ `例: deepseek/deepseek-v4-flash-vision-exp` に更新。

- [ ] **Step 2: chat-settings.js — 参照削除＋バリデーション追加**

1. **L39 削除**: `set("chat-provider", cfg.provider);`
2. **L100 削除**: `onChatProviderChange();`（applyChatConfig 内）
3. **L347-354 削除**: `function onChatProviderChange() { ... }` 全体
4. **L365 削除**: `provider: document.getElementById("chat-provider").value,`
5. **L588 削除**: `onProviderChange: onChatProviderChange,`（名前空間登録）
6. **saveChatConfig 冒頭（L357-360 の persona チェック直後）に追加**:

```javascript
  const baseUrlVal = (document.getElementById("chat-base-url")?.value || "").trim();
  if (!baseUrlVal) {
    toast("Base URL は必須です", "error");
    return;
  }
```

- [ ] **Step 3: 構文チェック**

Run: `node --check nous/api/http/static/chat/chat-settings.js`
Expected: エラー出力なし（node 未導入なら `python -c "print('skip')"` でスキップし Task 4 のブラウザ確認で代替）

- [ ] **Step 4: 残存参照チェック**

Run: `grep -r "onProviderChange\|chat-provider" nous/`
Expected: 0件（chat_sidebar_core.py と chat-settings.js 両方から消えていること。`chat-image-caption-provider` は別物なのでヒットさせてよいが `chat-provider"` の完全一致は無いこと）

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/sections/chat/chat_sidebar_core.py nous/api/http/static/chat/chat-settings.js
git commit -m "feat(ui): プロバイダードロップダウン廃止、base_url 必須化（OpenAI互換統一）"
```

---

### Task 4: 全体検証＋GATE

**Files:**
- Read only（変更なし、検証とコミットのみ）

**Interfaces:**
- Consumes: Task 1-3 の全変更
- Produces: 検証結果レポート

- [ ] **Step 1: ユニットテスト全実行**

Run: `python -X utf8 -m pytest tests/unit -q`
Expected: FAIL 0（既存テストの provider 依存は全て get_provider を mock しているため影響なし。FAIL があれば Task 1-3 に差し戻し）

- [ ] **Step 2: lint / format**

Run: `ruff check nous/ tests/` ＋ `ruff format --check nous/infrastructure/llm/factory.py nous/infrastructure/llm/openai_compat.py`
Expected: エラー 0（プロジェクトの lint 設定に従う。ruff 未導入なら設定済みツールに読み替え）

- [ ] **Step 3: ドキュメント同期チェック**

Run: `grep -rn "プロバイダー" docs/ README.md --include="*.md" | grep -v superpowers`
Expected: プロバイダードロップダウンを説明している箇所があれば更新（base_url 必須運用に合わせる。無ければ完了）

- [ ] **Step 4: 実ブラウザ確認（UI 変更は実機必須）**

1. Docker コンテナ nous が `/app/nous` を `:ro` マウントしているため、**コンテナ再起動で変更を反映**（`docker restart nous`、healthcheck 待ち）
2. `http://localhost:26262` を開き、チャット設定パネルで確認:
   - プロバイダー select が消え、Base URL が常時表示（必須ラベル）
   - Base URL を空にして保存 → toast「Base URL は必須です」で保存されない
   - Base URL `https://api.commandcode.ai/provider/v1` ＋ model `deepseek/deepseek-v4-flash-vision-exp` で保存成功
   - Reasoning ON ＋ チャット1ターン → 思考プロセス（ThinkingDeltaEvent 由来）が表示されれば実機 reasoning 修正も確認

- [ ] **Step 5: 実機 curl 4パターン（要 commandcode.ai API キー）**

キー未設定のためユーザー提供が必要。取得したら PowerShell:

```powershell
$key = "<COMMANDCODE_API_KEY>"
$body = @{model="deepseek/deepseek-v4-flash-vision-exp"; stream=$true; messages=@(@{role="user"; content="1+1は?"})} | ConvertTo-Json -Depth 5
# パターンA: effort のみ（修正前バグ再現 → reasoning_content 無いはず）
curl.exe -s -N https://api.commandcode.ai/provider/v1/chat/completions -H "Authorization: Bearer $key" -H "Content-Type: application/json" -d ($body + '"reasoning_effort":"high"}') 
# パターンB: + extra_body thinking/enable_thinking（修正後 → reasoning_content が出るはず）
```

判定期望: パターンA（effort のみ）で `reasoning_content` 無し → バグ再現確認。パターンB（`reasoning_effort` + `extra_body` 相当の top-level `thinking`/`enable_thinking`）で `reasoning_content` 有り → 修正有効確認。実サーバーは extra_body を展開しないため curl では top-level に置く点に注意（openai SDK の `extra_body` は送信時に top-level 展開される）。

- [ ] **Step 6: RECORD（記録フェーズ）**

GATE 通過後、nous 記憶に記録（tags: `project:nous`, `task_state`, kind=semantic, importance 0.75）。content にコミットハッシュ・変更概要・検証結果・「OpenAI互換サーバーは未知キーを黙って無視する」の教訓を含める。

---

## Self-Review 結果

- **Spec カバレッジ**: 設計①UI（Task 3）②factory 統一＋移行マップ（Task 2）③reasoning トグル（Task 1）④検証（各 Task のテスト＋Task 4）→ 全項目に対応タスクあり
- **プレースホルダー**: なし（全ステップに実コード記載）
- **型整合**: `get_provider` シグネチャ維持・戻り値型は `OpenAICompatProvider`（Task 2 の TYPE_CHECKING import で整合）。`test_openai_uses_reasoning_effort` の差し替え名は Step 1 と実装で一致
- **既存テスト保全**: `test_openrouter_uses_reasoning_object` は削除対象として明記（OpenRouter 分岐廃止とセット）。AnthropicProvider 系テスト（`TestAnthropicReasoning` 等）は anthropic.py 温存のため無傷
- **実機 curl のキー**: ユーザー提供待ちが既知ブロッカー（Task 4 Step 5 のみ依存、他は独立して完遂可能）
