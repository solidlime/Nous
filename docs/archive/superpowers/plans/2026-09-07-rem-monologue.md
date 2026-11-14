# REM Monologue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** REM drain 完了時に LLM が一人称独り言を生成・ログ保存し、再会ターンで system prompt に注入、処理中は SSE 表示バブルでライブ表示する。

**Architecture:** `EnrichmentWorker._run_cycle()` の drain 完了後に新設 `MonologueGenerator`（enricher と同一プロバイダ解決経路）を1呼び出し。結果は session_events（kind=`brain.monologue`）に保存＋wiring SSE に emit。チャットパイプラインは context_loader がギャップ条件判定と取得を行い、PromptBuildStep が `<monologue_context>` 兄弟タグを動的領域に注入。フロントは wiring feed と専用表示バブルで受ける。

**Tech Stack:** Python (pytest, mypy, ruff) / JS vitest (jsdom) / SQLite session_events / SSE

**Spec:** `docs/superpowers/specs/2026-09-07-rem-monologue-design.md`

## Global Constraints

- mypy 新規エラー 0（ベースライン 366）。ruff/format は変更ファイルのみ 0
- 注入タグは必ず `__STATIC_END__`（prompt.py:202）以降の動的領域に置く
- 生成・保存・emit は全て try/except + debug ログで包み、enrichment 本体を壊さない
- LLM 呼び出しは drain バッチごと 1 回のみ（記憶 1 件ごとではない）
- 素朴な assistant メッセージとしての保存は禁止（session_events のみ）
- 新規依存関係の追加禁止。CSP 準拠（インライン eval・style 属性直書き禁止、textContent/safeSetHTML 使用）
- 全 unit: pytest tests/unit 全緑 / vitest 全緑を各タスク終了時に確認
- コミットは TDD サイクルごと（RED→GREEN→commit）

## 実行レーン

- **レーンB（バックエンド, fixer）**: Task M1 → M2 → M3（直列）
- **レーンC（フロント, designer）**: Task C2 → C1（並行実行可。C1 の session_config キー名 `brain_monologue_enabled` は M1 で先行確定済みなので待ち合わせ不要）
- レーン間の write 衝突なし（B=Python のみ、C=JS + chat_sidebar_memory.py の HTML 部分のみ。B は chat_sidebar_memory.py に触れないこと）

---

### Task M1: brain_monologue_enabled キー + MonologueGenerator

**Files:**
- Create: `nous/infrastructure/llm/monologue_generator.py`
- Modify: `nous/domain/session_config.py:95-114`（brain_* 群に 1 行追加）
- Modify: `nous/application/use_cases.py:175` 付近 `_init_enricher`（generator 構築を追加）
- Test: `tests/unit/test_monologue_generator.py`（新規）

**Interfaces:**
- Consumes: `nous/infrastructure/llm/memory_enricher.py` の `_call_llm(provider, system, user_message) -> tuple[str | None, dict | None]`（:127-152）の stream 消費パターン、`get_provider(provider=..., api_key=..., model=..., base_url=...)`（:110-115）、`LLMMessage(role="user", content=...)`
- Produces: `MonologueGenerator(provider: LLMProvider)` + `async def generate(self, persona: str, memory_texts: list[str]) -> str | None`。`AppContext.monologue_generator: MonologueGenerator | None`（`_init_enricher` が enricher 解決成功時に同じ resolved provider 設定で構築、失敗時 None）

- [ ] **Step 1: session_config.py にキー追加**

`nous/domain/session_config.py` の brain_* 群（:110-114 付近、`brain_llm_dedicated` 群の直後）に:

```python
brain_monologue_enabled: bool = False
```

- [ ] **Step 2: 失敗するテストを書く**

```python
# tests/unit/test_monologue_generator.py
import pytest
from nous.infrastructure.llm.monologue_generator import MonologueGenerator


class FakeProvider:
    """_call_llm と同じ stream プロトコルを模倣するフェイク。"""

    def __init__(self, chunks=None, error=False):
        self._chunks = chunks or ["昨日の話、", "まだ頭に残ってる。"]
        self._error = error

    async def stream(self, messages=None, system=None, temperature=None, max_tokens=None):
        if self._error:
            yield ErrorEvent(error="boom")
            return
        for c in self._chunks:
            yield TextDeltaEvent(text=c)
        yield DoneEvent(usage={"prompt_tokens": 100, "completion_tokens": 20})


@pytest.mark.asyncio
async def test_generate_returns_joined_text():
    gen = MonologueGenerator(FakeProvider())
    out = await gen.generate("herta", ["記憶Aの本文", "記憶Bの本文"])
    assert out == "昨日の話、まだ頭に残ってる。"


@pytest.mark.asyncio
async def test_generate_error_returns_none():
    gen = MonologueGenerator(FakeProvider(error=True))
    assert await gen.generate("herta", ["x"]) is None


@pytest.mark.asyncio
async def test_generate_empty_memories_returns_none():
    gen = MonologueGenerator(FakeProvider())
    assert await gen.generate("herta", []) is None
```

（`TextDeltaEvent` / `DoneEvent` / `ErrorEvent` は `nous/infrastructure/llm/base.py` から import。fixture 化済みの類似 FakeProvider が既存テストにあれば流用してよい。）

- [ ] **Step 3: テスト実行 → FAIL**

Run: `python -m pytest tests/unit/test_monologue_generator.py -v`
Expected: FAIL（ModuleNotFoundError: monologue_generator）

- [ ] **Step 4: MonologueGenerator 実装**

```python
# nous/infrastructure/llm/monologue_generator.py
"""REM drain 完了時に一人称独り言を生成する。"""
from __future__ import annotations

import logging

from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, TextDeltaEvent
from nous.infrastructure.llm.provider import get_provider, LLMMessage  # memory_enricher.py と同一 import 経路

logger = logging.getLogger(__name__)

_MAX_MEMORIES = 5
_MAX_CHARS_PER_MEMORY = 80

_SYSTEM_TEMPLATE = (
    "あなたは{persona}。今は誰もいない場所で記憶を整理している。"
    "直近で処理した記憶をもとに、一人称の独り言を1〜3文で書け。"
    "会話ではない。質問・呼びかけ・挨拶を含めない。"
)


class MonologueGenerator:
    def __init__(self, provider):
        self._provider = provider

    @classmethod
    def from_config(cls, provider_name: str, api_key: str | None, model: str, base_url: str | None):
        provider = get_provider(provider=provider_name, api_key=api_key, model=model, base_url=base_url)
        return cls(provider)

    async def generate(self, persona: str, memory_texts: list[str]) -> str | None:
        if not memory_texts:
            return None
        lines = [
            f"- {t[:_MAX_CHARS_PER_MEMORY]}" for t in memory_texts[:_MAX_MEMORIES]
        ]
        user_message = "処理した記憶:\n" + "\n".join(lines)
        try:
            text, _usage = await self._call_llm(_SYSTEM_TEMPLATE.format(persona=persona), user_message)
        except Exception as exc:  # 失敗は静かに握る（spec §4.1）
            logger.debug("monologue generation failed: %s", exc)
            return None
        text = (text or "").strip()
        return text or None

    async def _call_llm(self, system: str, user_message: str) -> tuple[str | None, dict | None]:
        full_parts: list[str] = []
        usage = None
        async for event in self._provider.stream(
            messages=[LLMMessage(role="user", content=user_message)],
            system=system,
            temperature=0.7,
            max_tokens=200,
        ):
            if isinstance(event, TextDeltaEvent):
                full_parts.append(event.text)
            elif isinstance(event, ErrorEvent):
                return None, None
            elif isinstance(event, DoneEvent):
                usage = event.usage
        return ("".join(full_parts), usage)
```

（import 経路・イベント型名は `nous/infrastructure/llm/memory_enricher.py` の実コードに合わせて修正してよい。Provider 型が異なる場合は `memory_enricher.py` と同一の型ヒントを使う。）

- [ ] **Step 5: テスト実行 → PASS**

Run: `python -m pytest tests/unit/test_monologue_generator.py -v`
Expected: PASS

- [ ] **Step 6: use_cases.py で ctx に接続**

`_init_enricher`（use_cases.py:175-217）内: enricher 構築成功の箇所で、**同じ resolved 設定**（provider 名 / api_key / model / base_url のローカル変数）を使って

```python
self.monologue_generator = MonologueGenerator.from_config(provider_name, api_key, model, base_url)
```

を構築し `AppContext.monologue_generator` として公開（失敗経路では None）。provider が二重生成になる場合（get_provider のコスト）、同一 resolved 設定なら enricher の provider インスタンスを共有してもよい。**chat_llm_dedicated OFF 時の chat 流用解決鎖も自動的に引き継がれる**（同じ解決コードパスを通るため）。

- [ ] **Step 7: 既存テスト確認**

Run: `python -m pytest tests/unit/test_brain_llm_resolution.py tests/unit/test_enrichment_worker.py -q`
Expected: PASS（既存挙動を壊していないこと）

- [ ] **Step 8: Commit**

```bash
git add nous/infrastructure/llm/monologue_generator.py nous/domain/session_config.py nous/application/use_cases.py tests/unit/test_monologue_generator.py
git commit -m "feat(brain): add MonologueGenerator and brain_monologue_enabled config"
```

---

### Task M2: worker フック（生成・保存・emit）

**Files:**
- Modify: `nous/application/workers/enrichment_worker.py:84-116`（`_run_cycle` drain 完了後）
- Modify: `nous/domain/memory/wiring_events.py:26`（`WIRING_KINDS` に `"monologue"` 追加）
- Test: `tests/unit/test_enrichment_worker.py`（既存ファイルに追記）

**Interfaces:**
- Consumes: Task M1 の `AppContext.monologue_generator`、`MonologueGenerator.generate(persona, memory_texts) -> str|None`、`nous/domain/memory/session_event.py` の `SessionEvent(session_id, persona, event_type, summary, timestamp, detail=None, metadata=None)`、`session_event_repo.insert(event)` / `get_by_persona(persona, event_type, limit)`、`wiring_events.emit(kind, source="", target="", weight=0.0, meta=None)`
- Produces: session_events に `event_type="brain.monologue"` 行（`summary`=独り言本文、`metadata={"memory_keys": [...], "usage": {...}}`）。wiring SSE の `kind="monologue"` イベント（`meta={"persona": str, "text": str}`）

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_enrichment_worker.py` に追記（既存 fixture・fake repos パターンを踏襲）:

```python
class TestMonologueHook:
    def _worker_with_queue(self, ctx, cfg, pending_keys, memories):
        """既存の worker 構築ヘルパーがあるなら流用。queue.repo と memory_repo を fake で置換。"""
        ...

    def test_drain_nonempty_generates_monologue_and_saves_event(self, ...):
        # fake generator が "ふふ、いい夢だった。" を返すようにする
        # drain 2 件 → generator への memory_texts は 2 件分
        # session_event_repo に event_type="brain.monologue" で 1 行 insert されたこと
        # wiring emit が kind="monologue", meta={persona, text} で呼ばれたこと
        ...

    def test_drain_empty_does_not_call_generator(self, ...):
        # pending 0 件 → generator.generate が呼ばれない

    def test_disabled_config_does_not_call_generator(self, ...):
        # brain_monologue_enabled=False → generate 不呼び出し

    def test_generator_none_is_skipped_silently(self, ...):
        # ctx.monologue_generator=None → 何も起きず、drain は正常完了

    def test_session_event_insert_failure_does_not_break_cycle(self, ...):
        # repo.insert が raise → _run_cycle が例外を投げない

    def test_emit_uses_no_source_and_persona_meta(self, ...):
        # source="" / meta={"persona": ..., "text": ...} を assert
```

- [ ] **Step 2: テスト実行 → FAIL**

Run: `python -m pytest tests/unit/test_enrichment_worker.py -k monologue -v`
Expected: FAIL（フック未実装）

- [ ] **Step 3: wiring kind 追加**

`nous/domain/memory/wiring_events.py:26`:

```python
WIRING_KINDS = frozenset(["link_fire", "recall_boost", "ppr_hit", "replay_fire", "novelty_gate", "monologue"])
```

- [ ] **Step 4: フック実装**

`enrichment_worker.py` の `_run_cycle()`（:84）: drain ループ（:108-116）で各件の `memory.content` と `memory.key` が手に入るので、ループ内で `(key, content)` をリストに集める。ループ完走後:

```python
def _maybe_monologue(self, drained: list[tuple[str, str]]) -> None:
    cfg = self._config
    if not drained:
        return
    if not getattr(cfg, "brain_monologue_enabled", False):
        return
    generator = getattr(self.context, "monologue_generator", None)
    if generator is None:
        return
    texts = [c for _k, c in drained]
    try:
        text = self._run_async(generator.generate(self._persona, texts))
    except Exception as exc:
        logger.debug("monologue generate failed: %s", exc)
        return
    if not text:
        return
    keys = [k for k, _c in drained]
    # session_events 保存
    try:
        repo = getattr(self.context, "_session_event_repo", None)
        if repo is not None:
            repo.insert(SessionEvent(
                session_id="unknown",
                persona=self._persona,
                event_type="brain.monologue",
                summary=text,
                timestamp=get_now(),
                metadata={"memory_keys": keys},
            ))
    except Exception as exc:
        logger.debug("monologue event insert failed: %s", exc)
    # wiring SSE emit
    try:
        emit("monologue", meta={"persona": self._persona, "text": text})
    except Exception as exc:
        logger.debug("monologue wiring emit failed: %s", exc)
```

（`get_now` は `nous/domain/shared/time_utils.py` の既存ユーティリティ、`emit` は `wiring_events.py` の既存 singleton emit。既存テストの `_run_async` ブリッジ・persona 情報の保持方法に合わせて変数名は調整。）`_run_cycle()` 末尾で `self._maybe_monologue(drained)` を呼ぶ。

- [ ] **Step 5: テスト実行 → PASS**

Run: `python -m pytest tests/unit/test_enrichment_worker.py -q`
Expected: PASS（既存 idle/novelty テストも含めて）

- [ ] **Step 6: Commit**

```bash
git add nous/application/workers/enrichment_worker.py nous/domain/memory/wiring_events.py tests/unit/test_enrichment_worker.py
git commit -m "feat(brain): generate monologue after REM drain and persist/emit it"
```

---

### Task M3: 再会時注入（context_loader + prompt.py）

**Files:**
- Modify: `nous/application/chat/pipeline/context_loader.py:357-411`（`REUNION_GAP_SECONDS = 900` 定数抽出＋ギャップ中エントリ取得）
- Modify: `nous/application/chat/pipeline/prompt.py:163-198`（dynamic_parts に `<monologue_context>` 追加）
- Modify: `nous/application/chat/pipeline/context.py`（必要なら turn_ctx フィールド追加。P 計画の教訓: フィールド共有より return 値伝播を優先するが、Step 間の既存パターンに従う）
- Test: `tests/unit/test_monologue_injection.py`（新規）＋既存 `test_prompt_adherence.py` のタグ対検証は新タグ追加で自動的にカバーされるはず（崩れたら原因を調査）

**Interfaces:**
- Consumes: `state.last_conversation_time`、`session_event_repo.get_by_persona(persona, "brain.monologue", limit=10)`、`ChatConfig.brain_monologue_enabled`
- Produces: system prompt の動的領域に `<monologue_context>...</monologue_context>`（開閉対・内容に生 `<` なし）

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_monologue_injection.py
"""再会時 monologue 注入のテスト。既存 pipeline テストの fixture パターンを踏襲すること。"""

def test_injection_when_gap_over_900s_and_entries_exist(...):
    # last_conversation_time = now - 2h
    # session_event_repo に brain.monologue を 3 件（1 件は last_conversation_time より前）
    # → system_prompt に <monologue_context> が含まれ、ギャップ後の 2 件のみが載る
    # → タグ内に「再会」「1つまで」のフレーミング文言が含まれる

def test_no_injection_when_gap_under_900s(...):
    # last_conversation_time = now - 5min → <monologue_context> なし

def test_no_injection_when_all_entries_older_than_gap(...):
    # エントリが全部 last_conversation_time より前 → 注入なし

def test_no_injection_when_disabled(...):
    # brain_monologue_enabled=False → 注入なし

def test_no_injection_when_repo_none(...):
    # ctx._session_event_repo=None → 注入なし・例外なし

def test_injection_after_static_end(...):
    # 生成済み system_prompt の "__STATIC_END__" マーカーより後に <monologue_context> があること

def test_tag_pair_no_raw_lt_in_body(...):
    # タグ本文中に "<"（タグ記法に使われる生の開き角括弧）が含まれないこと
```

- [ ] **Step 2: テスト実行 → FAIL**

Run: `python -m pytest tests/unit/test_monologue_injection.py -v`
Expected: FAIL

- [ ] **Step 3: context_loader.py 定数抽出＋取得**

context_loader.py:357-411 `_build_time_context` 付近。ハードコードの 900s（:386）を:

```python
REUNION_GAP_SECONDS = 900  # 再会判定の閾値（time_context 表示と monologue 注入の共通条件）
```

として定数化し、既存の :386 の比較を `REUNION_GAP_SECONDS` に置換。さらに monologue エントリ取得:

```python
def _fetch_monologue_entries(ctx, state, config) -> list[str]:
    """ギャップ中に生成された独り言（直近3件・古い順）を返す。"""
    if not getattr(config, "brain_monologue_enabled", False):
        return []
    repo = getattr(ctx, "_session_event_repo", None)
    lct = getattr(state, "last_conversation_time", None)
    if repo is None or lct is None:
        return []
    try:
        events = repo.get_by_persona(state.persona, "brain.monologue", limit=10)
    except Exception as exc:
        logger.debug("monologue fetch failed: %s", exc)
        return []
    recent = [
        e.summary for e in sorted(events, key=lambda e: e.timestamp)
        if e.timestamp > lct and e.summary
    ][-3:]
    return recent
```

結果は turn_ctx に渡す（既存の Step 間データ受け渡しパターンに合わせる。turn_ctx 新規フィールド追加か戻り値伝播のいずれか——mypy 新規 0 を維持できる方を選ぶこと）。

- [ ] **Step 4: prompt.py にタグ描画**

`prompt.py` run（:101-206）の dynamic_parts 構築部（`<precedence>` :197 の直前あたり）に:

```python
if turn_ctx.monologue_entries:  # 前ステップで取得済み（空なら描画しない）
    lines = [l.replace("<", "＜").replace(">", "＞") for l in entries]
    body = "最終会話からしばらくが経過している。この間、あなたは独り言として次のように考えていた:\n" + "\n".join(f"- {l}" for l in lines)
    body += "\n再会直後の挨拶で自然に触れてよい。参照は1つまで。日記の読み上げをしないこと。ユーザーの入力が再会の挨拶でない場合は触れない。"
    dynamic_parts.append(f"<monologue_context>\n{body}\n</monologue_context>")
```

（経過時間の人間可読表示「2時間」等は context_loader 側でギャップ分類済みの文言を流用してよい。重複実装しないこと。）

- [ ] **Step 5: テスト実行 → PASS**

Run: `python -m pytest tests/unit/test_monologue_injection.py tests/unit/test_prompt_adherence.py tests/unit/test_chat_pipeline.py -q`
Expected: PASS

- [ ] **Step 6: 既存全テスト**

Run: `python -m pytest tests/unit -q`
Expected: PASS（ベースライン 2292 以上）

- [ ] **Step 7: Commit**

```bash
git add nous/application/chat/pipeline/context_loader.py nous/application/chat/pipeline/prompt.py tests/unit/test_monologue_injection.py
git commit -m "feat(chat): inject monologue context on reunion turns"
```

---

### Task C2: 表示専用思考バブル（designer レーン）

**Files:**
- Modify: `nous/api/http/static/chat/chat-send.js`（wiring ストリーム受信＋バブル描画）
- Modify: `nous/api/http/static/chat/chat-memory-panel.js:613` 付近（JS 側 `WIRING_KINDS` マップに `"monologue"` 追加）
- Modify: `nous/api/http/static/styles/chat.css`（`.chat-monologue-bubble`）
- Test: `nous/api/http/static/chat/chat-tools.test.js` or 新規 `chat-monologue.test.js`

**Interfaces:**
- Consumes: `N.Core.connectStream(name, opts)`（core/sse.js 名前付きマルチストリーム。`connectWiring` :753 が `N.Core.connectStream("wiring", {handlers: {wiring: handleWiringMessage}})` の例）。SSE イベント形式は `event: wiring`、data に `{kind, meta: {persona, text}, ts}`。
- Produces: `.chat-monologue-bubble`（💭 斜体・薄色・`--text-secondary`）をチャットログへ描画。履歴非保存（リロードで消える）

- [ ] **Step 1: 失敗するテストを書く**

```js
// chat-monologue.test.js
// monologue wiring イベント → .chat-monologue-bubble が 1 つ生成され textContent に meta.text が入る
// 2 連続イベント → バブル 2 つ（append 動作）
// kind="replay_fire" → バブルは生成されない（monologue のみ）
// DOM には入るがチャット履歴配列/セッション保存 API は呼ばれない
// textContent でエスケープ（meta.text に HTML 断片が入っても描画はテキスト）
```

- [ ] **Step 2: テスト実行 → FAIL**

Run: `npx vitest run chat/chat-monologue.test.js`（workdir: nous/api/http/static）
Expected: FAIL

- [ ] **Step 3: 実装**

`chat-send.js`:
- init 時に `N.Core.connectStream("wiring-chat", {url: <wiring エンドポイント>, handlers: {wiring: handleMonologueWiring}})` を張る（**"wiring" という名前は chat-memory-panel が使用中なので衝突しない別名を使う**。url・ハンドラ引数の正確な形は core/sse.js と connectWiring 実装を確認して踏襲）。
- `handleMonologueWiring(evt)`: `evt.kind === "monologue"` のときのみ、チャットログコンテナ（assistant バブルと同じ親）に:

```js
function appendMonologueBubble(text) {
    const bubble = document.createElement("details");
    bubble.className = "chat-monologue-bubble";
    const summary = document.createElement("summary");
    summary.textContent = "💭";
    const body = document.createElement("div");
    body.className = "chat-monologue-text";
    body.textContent = text;  // CSP-safe: textContent 直書き
    bubble.append(summary, body);
    chatLog.appendChild(bubble);
}
```

- 保存 API・履歴配列には触れない（表示のみ）。
- `chat-memory-panel.js` の `WIRING_KINDS` JS マップ（:613 付近）に `"monologue": "独り言"` を追加（pushWiringEvent :690 が未知 kind を弾くため）。パネル側の source 空表示は既存 fallback で OK。

`chat.css`:

```css
.chat-monologue-bubble {
    font-style: italic;
    color: var(--text-secondary);
    opacity: 0.85;
    font-size: 0.92em;
    /* 💭 思考バブルとしての静けさ。既存 .chat-thinking-bubble の余白トークンを踏襲 */
}
```

（既存 `--text-secondary`・余白トークン variables.css の語彙のみ使用。新トークン追加禁止。）

- [ ] **Step 4: テスト実行 → PASS**

Run: `npx vitest run`（全ファイル）
Expected: PASS（ベースライン 171 以上）

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/static/chat/chat-send.js nous/api/http/static/chat/chat-memory-panel.js nous/api/http/static/chat/chat-monologue.test.js nous/api/http/static/styles/chat.css
git commit -m "feat(webui): live monologue thinking bubble from wiring stream"
```

---

### Task C1: 設定トグル（designer レーン）

**Files:**
- Modify: `nous/api/http/sections/chat/chat_sidebar_memory.py:147-173`（`_BRAIN_HELP` 辞書＋ `_render_brain_simulation_section`）
- Modify: `nous/api/http/static/chat/chat-settings.js`（load :317-341 / save :362+）
- Test: `nous/api/http/static/chat/chat-settings-brain.test.js`（既存ファイルに契約テスト追記）

**Interfaces:**
- Consumes: Task M1 で追加済みの `brain_monologue_enabled`（デフォルト False）
- Produces: `POST /api/chat/{persona}/config` の payload に `brain_monologue_enabled` が乗る round-trip

- [ ] **Step 1: 失敗するテストを書く**

`chat-settings-brain.test.js` に追記（既存 brain_llm_dedicated テストのパターンを踏襲）:

```js
// brain_monologue_enabled が save payload に含まれ、load で checkbox に反映される round-trip
```

- [ ] **Step 2: テスト実行 → FAIL**

Run: `npx vitest run chat/chat-settings-brain.test.js`
Expected: FAIL

- [ ] **Step 3: 実装**

- `chat_sidebar_memory.py` `_render_brain_simulation_section`（:173）の「記憶強化（REM）」サブセクション内に checkbox 追加:

```html
<label class="settings-row">
    <input type="checkbox" id="chat-brain-monologue">
    <span>REM 独り言</span>
</label>
```

＋ `_BRAIN_HELP` に説明 1 行（例: `chat-brain-monologue: "REM 処理中に独り言を生成し、保存する。再会時に自然に触れるための記録"`）。
- `chat-settings.js` load 側: `setChecked("chat-brain-monologue", cfg.brain_monologue_enabled)` 相当。save 側: payload に `brain_monologue_enabled: document.getElementById("chat-brain-monologue").checked`。
- 依存フィールドの開閉はない（単独 checkbox）。delegation.js に新 case は不要（brain-llm-toggle と違い fields 切替がないため）。

- [ ] **Step 4: テスト実行 → PASS**

Run: `npx vitest run`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/sections/chat/chat_sidebar_memory.py nous/api/http/static/chat/chat-settings.js nous/api/http/static/chat/chat-settings-brain.test.js
git commit -m "feat(webui): REM monologue toggle in brain settings"
```

---

## 統合後（orchestrator）

1. #081 REVIEW（spec §4 の4条件・線量管理・try/except 慣習・キャッシュ境界を中心に correctness 反駁）
2. GATE: pytest 全体 / ruff 変更分 / mypy 新規 0 / vitest 全体
3. 実機検証: brain_enrich_auto_run=true + アイドル2分で drain 発火 → バブル表示・session_events 保存・（ギャップ後の再会ターンで）`<monologue_context>` 注入を確認
4. RECORD（nous 記憶、project:nous タグ）
