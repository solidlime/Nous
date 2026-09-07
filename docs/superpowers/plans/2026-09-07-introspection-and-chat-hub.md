# 内省エンジン＋チャット分離（SSEハブ） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 独り言をチャット欄に一本化し、ジャッジLLMをアイドル時内省に昇華、チャット処理をブラウザ接続から分離（SSEハブ）して切断耐性・複数クライアント同期を実現する。

**Architecture:** E2 は EnrichmentWorker の drain 後フックで新モジュール `introspection.py`（単一LLM呼び出しで独り言＋逸脱判定＋反省＋感情/身体delta）。E3 は既存 pipeline generator を無変更のまま消費者を StreamingResponse → サーバー内タスク＋TurnHub（リングバッファ600＋クライアント毎queue）へ差し替え。フロントは既存イベントハンドラ流用・供給源をハブSSEへ。

**Tech Stack:** Python (FastAPI/uvicorn/asyncio), SQLite, vanilla JS (CSP-safe, N.Core/N.Components 語彙), vitest (workdir `nous/api/http/static`), pytest, mypy (新規0), ruff。

**Spec:** docs/superpowers/specs/2026-09-07-introspection-engine-and-chat-hub-design.md（コミット 3778c42f）

## Global Constraints

- TDD: RED→GREEN→commit を各タスクで厳守。コミットは task 単位。
- mypy: 全プロジェクト 366 errors を超えない（新規 0）。ruff: 触れたファイル check+format 0。
- vitest は必ず workdir `nous/api/http/static` で実行（repo root からだと collection error）。
- CSP-safe: ランタイム eval 禁止、`esc()`/`safeSetHTML`/`textContent` 慣習、`core/delegation.js` 経由の data-action。
- cache boundary: system prompt への新注入は禁止（本計画では注入なし）。`__STATIC_END__` を跨ぐ変更をしない。
- worker スレッドからの async 呼び出しは `_run_async` ブリッジ（enrichment_worker.py:255/:302 パターン）。emit/insert は全 try/except + debug。
- 禁止: `git push --force` / `git commit --no-verify`。Python 変更はサーバー再起動必要、静的JSはリロードのみ（実機検証時）。
- mypy 既存山（use_cases.py の Failure.value 等）は触らない・直さない。

---

# Lane A — E2 内省エンジン（fix-4）

### Task A1: brain_introspection_enabled 設定キー

**Files:**
- Modify: `nous/domain/session_config.py:95-114`（brain キー群の末尾に追加）
- Test: `tests/unit/test_brain_llm_resolution.py`（既存パターン踏襲）

**Interfaces:**
- Produces: `SessionConfig.brain_introspection_enabled: bool = True`（ChatConfig Facade が `__getattr__` 委譲で自動解決 — chat_config.py:133-143、追加コード不要）

- [ ] Step 1: 失敗テスト（`test_brain_llm_resolution.py` に追加）

```python
def test_introspection_enabled_default_true():
    cfg = ChatConfig()
    assert cfg.brain_introspection_enabled is True

def test_introspection_config_persisted(tmp_path):
    repo = ChatConfigFileRepository(str(tmp_path))
    cfg = repo.get("p1")
    cfg.brain_introspection_enabled = False
    repo.save("p1", cfg)
    assert repo.get("p1").brain_introspection_enabled is False
```

- [ ] Step 2: RED 確認 → `pytest tests/unit/test_brain_llm_resolution.py -q`（attribute 不在で fail）
- [ ] Step 3: `session_config.py` の brain キー群に `brain_introspection_enabled: bool = True` を 1 行追加
- [ ] Step 4: GREEN 確認 → Commit `feat(brain): add brain_introspection_enabled config key`

### Task A2: introspection モジュール（単一LLM呼び出し）

**Files:**
- Create: `nous/application/chat/introspection.py`
- Modify: `nous/application/chat/monologue_generator.py`（from_config の provider 解決パターンを踏襲。クラス自体は Task A4 で利用終了後に削除）
- Test: `tests/unit/test_introspection.py`（新規）

**Interfaces:**
- Consumes: `MonologueGenerator.from_config(config) -> MonologueGenerator | None` の provider 解決（use_cases.py:232 の同一 resolved 鎖: brain_llm_dedicated/ON→専用5キー、OFF→chat 4点セット、cfg None→settings 鎖）。`ctx.persona_service.update_emotion / update_physical_state`（nous/domain/persona/service.py:57/:105）。`ctx.memory_service.create_memory`。`ctx.session_event_repo.get_by_persona(persona, event_type, limit)`（session_event_repo.py:59）。メッセージ取得は chat_stream.py:68-82 `_do_get_chat_session` と同一経路（`SessionManager.get_messages` — 実装者は同関数の呼び方をそのまま踏襲）。
- Produces:

```python
@dataclass
class IntrospectionResult:
    monologue: str | None
    violation: str | None
    violation_detail: str
    reflection: str | None
    emotion: dict | None          # {"emotion": str, "emotion_intensity": float}
    body_state: dict | None       # {"fatigue","warmth","arousal"} 0.0-1.0

class IntrospectionEngine:
    @classmethod
    def from_config(cls, config: ChatConfig) -> IntrospectionEngine | None: ...
    async def generate(self, persona: str, system_prompt: str,
                       recent_turns: list[dict], memory_texts: list[str]) -> IntrospectionResult | None: ...

def fetch_recent_turns(ctx: AppContext, since: datetime | None) -> list[dict]:
    """chat_sessions 直近12メッセージ(user+assistant)を時刻順に。合計8000字cap。since があれば time > since のみ。"""

async def run_introspection(ctx: AppContext, config: ChatConfig,
                            engine: IntrospectionEngine | None,
                            drained_texts: list[str]) -> None:
    """ガード→ターン取得→generate→適用（全段 try/except+debug、worker停止しない）。"""
```

プロンプト（temperature 0.7 / max_tokens 512 / JSON出力。memory_enricher.py の `_call_llm` パターンで usage debug ログも踏襲）:

```python
_INTROSPECTION_PROMPT = """あなたは {persona} です。
以下の資料から、一人称の独り言・内省結果を出力せよ。

【最近の会話】
{recent_turns}

【この間に記憶に刻んだこと】
{memory_texts}

【ペルソナ設定（逸脱判定の基準）】
{persona_identity}

【出力形式】JSONのみ。
{{
  "monologue": "独り言（最大5文・この間の出来事と気持ちを織り込む）",
  "violation": "キャラ逸脱があれば種別を一言。なければ null",
  "violation_detail": "逸脱の具体内容。なければ null",
  "reflection": "逸脱があった場合の一人称反省文1文。なければ null",
  "emotion": {{"emotion": "正典25語の感情名", "emotion_intensity": 0.0-1.0}},
  "body_state": {{"fatigue": 0.0-1.0, "warmth": 0.0-1.0, "arousal": 0.0-1.0}}
}}
感情・身体は会話から自然に推定した場合のみ記載し、変化なしなら null。
"""
```

- [ ] Step 1: 失敗テスト

```python
def test_fetch_recent_turns_filters_since(tmp_ctx):
    # chat_sessions に 4 メッセージ投入（user/assistant 2往復 + tool）
    # since より前の1件が除外され、tool が除外されること
    turns = fetch_recent_turns(tmp_ctx, since=cutoff)
    assert all(t["role"] in ("user", "assistant") for t in turns)

def test_generate_parses_json(monkeypatch):
    engine = IntrospectionEngine.from_config(_fake_config(monkeypatch))  # _call_llm を stub
    # stub が上記 JSON を返す
    r = await engine.generate("herta", "sp", [], [])
    assert r.monologue == "..."
    assert r.violation is None

def test_run_introspection_applies_state(tmp_ctx, monkeypatch):
    # engine stub: violation + emotion + monologue を返す
    await run_introspection(tmp_ctx, cfg, engine, drained_texts=["m1"])
    # 感情レコード追加・反省メモリ作成（tags ["character_drift","introspection"]）・
    # session_events に brain.monologue + brain.introspection が記録されること
    assert tmp_ctx.persona_repo.get_emotion_history(...).value[-1].context == "introspection"

def test_run_introspection_skips_when_no_new_turns(tmp_ctx):
    # 前回 brain.introspection 以降に新規ターン無し → generate 不呼び出し
def test_run_introspection_reflection_dedupe(tmp_ctx, monkeypatch):
    # 同一 violation+reflection が直近 character_drift に既存 → create_memory 不呼び出し
def test_run_introspection_respects_monologue_toggle(tmp_ctx, monkeypatch):
    # brain_monologue_enabled=False → brain.monologue 記録なし（判定・状態適用は実行）
```

- [ ] Step 2: RED 確認（`pytest tests/unit/test_introspection.py -q` → import error）
- [ ] Step 3: 実装。適用部の要旨:

```python
if r.emotion:
    ctx.persona_service.update_emotion(persona, EmotionRecord(
        emotion=r.emotion["emotion"], intensity=float(r.emotion["emotion_intensity"]),
        context="introspection"))          # _tools_persona.py:131 の呼び方を踏襲、値は clamp
if r.body_state:
    ctx.persona_service.update_physical_state(persona, BodyStateRecord(
        fatigue=..., warmth=..., arousal=..., context="introspection"))
if r.violation and r.reflection and not _dup_character_drift(ctx, r.reflection):
    ctx.memory_service.create_memory(..., tags=["character_drift", "introspection"], importance=0.8)
# monologue: brain_monologue_enabled 時のみ session_events INSERT + wiring emit
# （enrichment_worker.py:149/:158 の既存コードをこのモジュールへ移設）
# 最後に session_events に brain.introspection（メタ: violation 有無・適用内容）を記録
```

- [ ] Step 4: GREEN 確認 → Commit `feat(brain): add introspection engine (single-LLM judge + monologue + state)`

### Task A3: use_cases への組み込み

**Files:**
- Modify: `nous/application/use_cases.py:185-217`（`_init_enricher` 内、monologue generator 構築箇所の隣）

**Interfaces:**
- Produces: `AppContext.introspection_engine: IntrospectionEngine | None`。`reload_enricher()`（use_cases.py:267）で再構築される。

- [ ] `_init_enricher` で monologue generator と同一タイミング・同一 resolved 鎖で構築（失敗時 None + debug）。
- [ ] 失敗テスト: engine 無し config で None、reload で差し替わることを `test_brain_llm_resolution.py` に 2 件追加 → GREEN → Commit `feat(brain): wire introspection engine into AppContext`

### Task A4: worker フック置換

**Files:**
- Modify: `nous/application/workers/enrichment_worker.py:123-160`（`_maybe_monologue` → `_maybe_introspect(drained)`）
- Test: `tests/unit/test_enrichment_worker.py`（TestMonologueHook 6件を IntrospectionHook に書き換え）

- [ ] `_run_cycle` の drain ループ完走後の呼び出しを `_maybe_introspect(drained)` に変更。内部は `run_introspection(ctx, config, ctx.introspection_engine, drained_texts)` 1 行（ガードは introspection.py 側に集約済み）。
- [ ] テスト: drain ありで engine 呼び出し / drained 空でも新規ターンあれば呼び出し（新規テスト1件追加）/ disabled で呼び出し無し / 例外で worker 停止しない。RED→GREEN → Commit `feat(brain): run introspection after REM drain cycle`

### Task A5: post.py から毎ターン judge 廃止

**Files:**
- Modify: `nous/application/chat/pipeline/post.py:107-117, 207-226`（`_with_drift` と judge ブロック削除。`memory_result = await run_memory_llm(ctx, config, payload, ...)` に直す。`drift=payload.get("drift")` は残置 OK — payload に drift キーが無いので常に None）
- Test: `tests/unit/test_post_process_validation.py`（judge 呼び出し無し・memory_llm は従来通り呼ばれることを assert するテストに書き換え。`TestCharacterConsistencyGap` は introspection 側の A2 テストに役割移行）

- [ ] RED→GREEN → Commit `refactor(chat): remove per-turn character judge (moved to idle introspection)`

---

# Lane B — E3 チャット分離 SSEハブ（fix-5）

### Task B1: TurnHub モジュール

**Files:**
- Create: `nous/application/chat/turn_hub.py`
- Test: `tests/unit/test_turn_hub.py`（新規）

**Interfaces:**
- Produces:

```python
class TurnHub:
    """persona 毎のターンイベント配信。1 persona 同時1ターン。"""
    def __init__(self, buffer_size: int = 600, queue_size: int = 256) -> None: ...
    def begin_turn(self, persona: str) -> str | None:
        """turn_id 発行。実行中なら None（409 用）。"""
    def publish(self, persona: str, sse_str: str) -> None:
        """イベント文字列（evt.to_sse() の戻り値）をバッファ(seq 付与)＋全 subscriber queue へ。
        queue は put_nowait・満杯なら最古を drop（drop-oldest）。"""
    def publish_synthetic(self, persona: str, payload: dict) -> str:
        """{"type": "turn_started", ...} 等を合成発行し sse 文字列を返す。"""
    def snapshot_after(self, persona: str, last_seq: int) -> list[tuple[int, str]]: ...
    def subscribe(self, persona: str) -> asyncio.Queue: ...
    def unsubscribe(self, persona: str, queue: asyncio.Queue) -> None: ...
    def end_turn(self, persona: str) -> None:
        """実行フラグ解除。バッファは残置（遅延接続のリプレイ用）。"""
```

- [ ] 失敗テスト: begin→busy None / publish→buffer+subscriber 受信 / 溢れ drop-oldest / snapshot_after 差分 / end→再 begin 可能 / unsubscribe 後は届かない。RED→GREEN → Commit `feat(chat): add per-persona turn hub with replay buffer`

### Task B2: Router 分離（POST 202 ＋ events SSE）

**Files:**
- Modify: `nous/api/http/routers/chat/chat_stream.py`（`_do_chat` StreamingResponse を置換）
- Modify: `nous/application/chat/service.py`（クラスに `chat_turn` ラッパー追加 — generator は無変更）
- Test: `tests/unit/test_chat_service.py` 追加＋ `tests/unit/test_chat_stream_router.py`（新規）

**Interfaces:**
- Consumes: Task B1 の TurnHub。SSE クラスの `to_sse()`（nous/application/chat/events.py 各 dataclass）。
- Produces:
  - `POST /api/chat/{persona}` → 202 `{"turn_id": "..."}`（実行中 409 `{"detail": "turn already running"}`）。body は現行のまま `{message, session_id, debug}`。
  - `GET /api/chat/{persona}/events?last_seq=0` → SSE。接続時 `snapshot_after(last_seq)` リプレイ（`id: <seq>` 付き）→ ライブ push。keepalive 15s、`request.is_disconnected()` 監視（routers/events.py:126 パターン）。
  - ハブは生成子の先頭で `publish_synthetic({"type": "turn_started", "user_message": ..., "session_id": ...})`。

`chat_turn` ラッパー（service.py に追加。pipeline generator `self.chat(...)` は無変更）:

```python
async def chat_turn(self, ctx, config, message, session_id="main", debug=False) -> str:
    """ターンをサーバー内タスクで完遂し、全SSEイベントをハブへ配信する。"""
    turn_id = self._hub.begin_turn(ctx.persona)
    if turn_id is None:
        raise TurnBusyError(ctx.persona)
    self._hub.publish_synthetic(ctx.persona, {
        "type": "turn_started", "user_message": message, "session_id": session_id})
    async def _consume() -> None:
        try:
            async for evt in self.chat(ctx, config, message, session_id=session_id, debug=debug):
                self._hub.publish(ctx.persona, evt.to_sse())
        except Exception:
            self._hub.publish_synthetic(ctx.persona, {"type": "error", "message": "internal error"})
            logger.exception("chat_turn failed persona=%s", ctx.persona)
        finally:
            self._hub.end_turn(ctx.persona)
    asyncio.create_task(_consume())
    return turn_id
```

Router:

```python
@router.post("/{persona}")
async def chat(persona: str, body: ChatRequest):
    # 現行の ctx/config 解決コードを流用
    try:
        turn_id = await service.chat_turn(ctx, config, body.message, body.session_id, body.debug)
    except TurnBusyError:
        return JSONResponse({"detail": "turn already running"}, status_code=409)
    return JSONResponse({"turn_id": turn_id}, status_code=202)

@router.get("/{persona}/events")
async def chat_events(persona: str, request: Request, last_seq: int = 0):
    # snapshot_after リプレイ → queue ライブ → keepalive 15s → is_disconnected
```

- [ ] テスト（fake generator で pipeline を置換）: 202 + turn_id / 409 / タスク完遂で done がバッファに積まれる / turn_started 合成 / 例外でも end_turn / リプレイ順序。RED→GREEN → Commit `feat(chat): decouple turn execution from response streaming (202 + hub SSE)`
- [ ] **注意**: 旧 `/api/chat/{persona}` の SSE レスポンス契約は本コミットで消える。フロント（Task C5）が着地するまでローカル実機確認はしない（vitest＋pytest のみで OK、最終 GATE 前に統合確認）。

### Task B3: 設定同期イベント

**Files:**
- Modify: `nous/api/http/routers/events.py:32-42`（`_ALL_EVENT_TYPES` に `"config.updated"` 追加）
- Modify: `nous/api/http/routers/chat/chat_management.py`（`save_chat_config` 成功時 `EventBus.publish("config.updated", {...})` — 既存 publish 呼び出し（例: tool.called）と同シグネチャで persona/payload を設定）
- Test: `tests/unit/test_config_updated_event.py`（新規 — save 後に EventBus を購読して受信 1 件）

- [ ] RED→GREEN → Commit `feat(webui): broadcast config.updated on settings save`

### Task B4: TreeSession 即時 persist

**Files:**
- Modify: `nous/application/chat/tree_session.py:91-92`（batch_size=10 ゲート撤去、`add()` は毎回 `_persist()`）
- Test: `tests/unit/test_chat_service.py` の session 系に「user メッセージ追加直後に DB から読み取れる」1 件追加

- [ ] RED→GREEN → Commit `fix(chat): persist chat messages immediately (browser-close safe)`

---

# Lane C — E1/E4/E3フロント（des-5）

### Task C1: 発火パネルから monologue 除外

**Files:**
- Modify: `nous/api/http/static/chat/chat-memory-panel.js`（JS 側 `WIRING_KINDS` マップから `monologue: "独り言"` を削除 — pushWiringEvent が未知 kind を弾くためこれだけ）
- Test: `nous/api/http/static/chat/chat-wiring-feed.test.js`（monologue イベントがフィードに積まれない assert に書き換え）

- [ ] RED→GREEN → Commit `refactor(webui): remove monologue from wiring feed panel`

### Task C2: mem-modal keyless ガード

**Files:**
- Modify: `nous/api/http/static/components/mem-modal.js:147-160`（`mem.key` 不在時 Edit/Delete を非表示。Copy/タグは残す）
- Test: `nous/api/http/static/components/mem-modal.test.js`（keyless openMemory でボタン無し）

- [ ] Commit `feat(webui): hide edit/delete for keyless memory previews`

### Task C3: 💭バブル→内容モーダル

**Files:**
- Modify: `nous/api/http/static/chat/chat-send.js`（`handleMonologueWiring` のバブル生成箇所。summary クリック → `N.Components.memModal.openMemory({content: text, tags: ["monologue"]})`。CSP-safe: summary に data 属性＋既存 delegation か、バブル生成時に addEventListener（既存バブル生成コードの慣習に従う））
- Test: `nous/api/http/static/chat/chat-monologue.test.js`（クリック→openMemory 呼び出し 1 件追加）

- [ ] Commit `feat(webui): monologue bubble opens content modal`

### Task C4: バブル復元（履歴読み込み時）

**Files:**
- Modify: `nous/api/http/static/chat/chat-history.js`（履歴復元後に `GET /api/session-events?persona={p}&event_type=brain.monologue&limit=20` を取得（routers/session_events.py:55 の event_type フィルタを踏襲。実装者は現エンドポイントの実パラメータを確認）、💭バブルを履歴メッセージの直後に描画。`clearWiring` 相当のリセット＋persona 切替で再取得）
- Test: `nous/api/http/static/chat/chat-monologue.test.js`（復元描画・persona 切替再取得 2 件）

- [ ] Commit `feat(webui): restore monologue bubbles from session events on history load`

### Task C5: chat-send を SSEハブ購読へ置換（fix-5 の Task B2 着地後）

**Files:**
- Modify: `nous/api/http/static/chat/chat-send.js`（fetch-stream 読み取り → `N.Core.connectStream("chat-events", {url: () => "GET /api/chat/{persona}/events?last_seq=" + _chatLastSeq, handlers: {...}})`。既存イベントハンドラ群（text_delta/tool_call/done/debug 等）は流用し供給源をハブへ。`chatSend()` は POST→202→SSE 確認。409 は toast。再接続時 last_seq 送り差分受信、done で bubble 最終化）
- Modify: `nous/api/http/static/base.js`（persona 切替の connectSSE wrap funnel に "chat-events" 再スコープ追加 — monologue wrap パターン踏襲）
- Test: `nous/api/http/static/chat/chat-send.test.js`（202 解析/SSE 購読/turn_started 描画/409 toast/reconnect last_seq）

- [ ] Commit `feat(webui): chat send rides the server-side turn hub stream`

### Task C6: E4 軽微修正

**Files:**
- Modify: `nous/api/http/static/styles/components.css:1418-1419`（`.wiring-detail-chip` の `rgba(191,90,242,…)` → `color-mix(in srgb, var(--accent-purple) 12%, transparent)` / border 30%）
- Modify: `nous/api/http/static/chat/chat-memory-panel.js:952,969`（wiring-detail-overlay 開閉を `classList.add/remove("active")` へ — components.css:990-994 の規約）
- Modify: `nous/api/http/static/chat/chat-memory-panel.js` `openPanelDetail`（append と `.show` の間に `void overlay.offsetWidth` 強制 reflow）
- Test: `nous/api/http/static/chat/chat-wiring-feed.test.js`（active クラストグル 1 件）

- [ ] Commit `fix(webui): theme tokens and class-toggle for wiring detail modal`

### Task C7: 設定同期リスナー

**Files:**
- Modify: `nous/api/http/static/core/sse.js`（`/api/events/{persona}` のトピック購読に `config.updated` を追加し、ハンドラ＝設定パネル表示中なら debounced 設定再読込）
- Test: `nous/api/http/static/core/sse.test.js`（config.updated 受信→再読込トリガ 1 件）

- [ ] Commit `feat(webui): reload settings panel on config.updated`

---

# 実行順序とレーン

1. **並行開始可**: fix-4（Lane A 全部）/ fix-5（Lane B 全部）/ des-5（Lane C の C1-C4, C6-C7）— ファイル衝突なし（C5 のみ chat-send.js を fix-5 非干渉で des-5 が独占）。
2. **依存**: C5 は B2 着地後。B4（tree_session）は B2 と同レーン内で先行実施可。
3. **統合後**: ora-3 で REVIEW（diff 全量・spec 照合）→ GATE（pytest 全体 / vitest / mypy 新規0 / ruff）→ 実機検証（Playwright: 切断耐性・2クライアント・内省実行・バブルモーダル・テーマ）→ RECORD。
