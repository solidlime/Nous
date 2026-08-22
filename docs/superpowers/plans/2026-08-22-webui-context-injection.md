# webui コンテキスト注入強化 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SPEC-webui-context-injection.md の実装 — opencode で記録した記憶が webui チャットに自動引き継がれるようにする（recency digest 注入 + recall 強化 + trimmer 優先度変更 + 設定監査修正）。

**Architecture:** PrepareStep が直近記憶ダイジェストを構築し、InferenceStep が最新 user 発言の直前に合成メッセージとして注入（非永続化・毎ターン再構築）。既存 `memory_service.get_recent()`（ORDER BY updated_at DESC 済）を再利用。設定は CompressionConfig に `memory_digest_count` を新設。

**Tech Stack:** Python 3.x / pydantic v2 / FastAPI / SQLite / vanilla JS (chat-settings.js)

## Global Constraints

- テスト実行はシステム python3（`.venv/bin/python -> /usr/bin/python3`）。`make test` = `pytest tests/unit/ -q`
- lint: ruff / 型: mypy（既存エラーのみ変更起因なしで可）
- ハードコード禁止・既存パターン踏襲（clamp validator、sidebar HTML パターン、JS wiring パターン）
- 禁止操作: `git push --force` / `git commit --no-verify`
- spec 前提と実装の差分（調査確定済み）:
  - `get_by_tags` は SQL 実装で既に `ORDER BY updated_at DESC`（memory_stats_mixin.py:96）→ session_summary sort 対策は不要（回帰テストのみ）
  - digest データソースは既存 `get_recent()`（memory_crud_repo.py:115 同 ORDER BY）を再利用
  - 現行クエリは「user + last_assistant[:200]」の2クエリ（memory_retriever.py:65-67）→ §2 はこれを置換
  - JS wiring は 178=read / 392=set（spec 記述と逆）
  - 14項目の実体は ToolConfig（tool_config.py）/ SessionConfig（session_config.py）、ChatConfig._all_flat_fields() 経由でフラット保存

---

### Task 1: compression_config.py — memory_digest_count 新設 + preload 既定値変更（Lane B）

**Files:**
- Modify: `nous/domain/compression_config.py:21` 付近
- Test: `tests/unit/test_compression_config.py`（無ければ新規）

**Interfaces:**
- Produces: `CompressionConfig.memory_digest_count: int = 5`（0=無効）、`memory_preload_count` 既定 5

- [ ] **Step 1: 失敗テスト**

```python
from nous.domain.compression_config import CompressionConfig

def test_memory_digest_count_default_and_clamp():
    c = CompressionConfig()
    assert c.memory_digest_count == 5
    assert CompressionConfig(memory_digest_count=-1).memory_digest_count == 0
    assert CompressionConfig(memory_digest_count=99).memory_digest_count == 20

def test_memory_preload_count_default_is_5():
    assert CompressionConfig().memory_preload_count == 5
```

- [ ] **Step 2: 実装** — `memory_preload_count: int = 3` を `= 5` に。`memory_digest_count: int = 5  # 0=無効` を直後に追加。validator は `_clamp_preload_count`（41-44行）と同型で `_clamp_digest_count`（max(0, min(20, v))）を追加。
- [ ] **Step 3: pytest で PASS 確認 → commit せず Lane B の他タスクと一括コミット**

### Task 2: chat_config.py — _infer_default_value pydantic default 対応（§5）（Lane B）

**Files:**
- Modify: `nous/domain/chat_config.py:266-270`
- Test: 既存 chat_config リポジトリテストファイルに追加（glob `tests/unit/*chat_config*` で特定、無ければ新規）

**Interfaces:**
- Produces: ALTER TABLE の DEFAULT が pydantic field default と一致する

- [ ] **Step 1: 失敗テスト**

```python
def test_infer_default_value_uses_pydantic_default():
    from nous.domain.chat_config import ChatConfig, ChatConfigRepository
    f = ChatConfig._all_flat_fields()
    # int 既定値がそのまま入る（旧実装だと "0"）
    assert ChatConfigRepository._infer_default_value(f["memory_digest_count"]) == "5"
    # bool True 既定（旧実装だと "0"）
    assert ChatConfigRepository._infer_default_value(f["context_compress_system_prompt"]) == "1"
    # str 既定
    assert ChatConfigRepository._infer_default_value(f["system_prompt"]) == "''"
```

- [ ] **Step 2: 実装**

```python
@staticmethod
def _infer_default_value(field_info) -> str:
    """Infer SQL DEFAULT expression from a Pydantic FieldInfo (pydantic default 優先)."""
    base = ChatConfigRepository._get_base_type(field_info.annotation)
    _, type_default = _TYPE_SQL.get(base, ("TEXT", "''"))
    default = getattr(field_info, "default", None)
    if default is PydanticUndefined:
        factory = getattr(field_info, "default_factory", None)
        try:
            default = factory() if factory else None
        except Exception:
            default = None
    if default is None:
        return type_default
    if base is bool:
        return str(int(bool(default)))
    if base is int:
        return str(int(default))
    if base is float:
        return str(float(default))
    return "'" + str(default).replace("'", "''") + "'"
```

import 追加: `from pydantic_core import PydanticUndefined`（pydantic v2）。
- [ ] **Step 3: pytest PASS 確認**

### Task 3: provider_config.py — reasoning_effort validator clamp 化（§6）（Lane B）

**Files:**
- Modify: `nous/domain/provider_config.py:102-107`
- Test: `tests/unit/test_provider_config.py`

- [ ] **Step 1: 失敗テスト**: `ProviderConfig(reasoning_effort="bogus")` が raise せず `"medium"` になること（REASONING_EFFORTS 定義とフィールド既定を確認し既定値を採用）
- [ ] **Step 2: 実装**: raise をやめ `return "medium"`（既定値）へフォールバック:

```python
@field_validator("reasoning_effort")
@classmethod
def _validate_reasoning_effort(cls, v: str) -> str:
    if v in REASONING_EFFORTS:
        return v
    return "medium"  # 不正値は既定へ clamp（設定全体のデフォルトフォールバック防止）
```

- [ ] **Step 3: pytest PASS 確認**

### Task 4: post.py — auto_capture interval throttle（§6）（Lane B）

**Files:**
- Modify: `nous/application/chat/pipeline/post.py:122-139`
- Test: `tests/unit/test_auto_capture_kind.py` に追加 or 近接テストファイル

**Interfaces:**
- Consumes: `config.auto_capture_interval`（SessionConfig 由来、ChatConfig フラット参照。getattr フォールバック 300）

- [ ] **Step 1: 失敗テスト**: 【別インスタンスで検証すること】PostProcessStep を2回新規生成し、interval 未達の2連続呼び出しで run_auto_capture が1回しか呼ばれないこと（run_auto_capture をパッチ）。interval=0 なら毎回呼ばれること。（#081 指摘: service.py:264 で毎ターン新規インスタンス化されるため同一インスタンス再利用のテストは無意味）
- [ ] **Step 2: 実装** — モジュールレベル変数（persona キー付き。インスタンス属性は毎ターン初期化され機能しない）:

```python
# module level: persona ごとの最終 auto_capture 実行時刻（monotonic）
_last_auto_capture_at: dict[str, float] = {}
```

auto_capture ブロック冒頭に:

```python
import time
interval = max(0, int(getattr(config, "auto_capture_interval", 300)))
now = time.monotonic()
last = _last_auto_capture_at.get(ctx.persona)
due = interval <= 0 or last is None or (now - last) >= interval
if config.auto_capture_enabled and session._messages and due:
    _last_auto_capture_at[ctx.persona] = now
    ...（既存の create_task）...
```

- [ ] **Step 3: pytest PASS 確認**

### Task 5: パイプライン本体 — §1 digest / §2 クエリ拡張 / §3 trim 順序 / §4 指示 / task_state 注入 / tz 修正（Lane A）

**Files:**
- Modify: `nous/application/chat/pipeline/context.py`（turn_ctx フィールド追加）
- Modify: `nous/application/chat/pipeline/prepare.py`（digest 構築 + クエリ拡張 + preload リテラル）
- Modify: `nous/application/chat/pipeline/inference.py`（digest 注入 + tz 表記修正）
- Modify: `nous/application/chat/pipeline/compress.py`（Stage 1↔2 入替）
- Modify: `nous/application/chat/pipeline/prompt.py:51-54`（§4 一行）
- Modify: `nous/application/chat/pipeline/context_loader.py:247` 後（task_state 注入）
- Test: `tests/unit/test_chat_pipeline.py` へ追加

**Interfaces:**
- Consumes: `CompressionConfig.memory_digest_count`（Task 1）、`ctx.memory_service.get_recent(limit)`、`relative_time_str`（nous/domain/shared/time_utils.py:35、context_loader.py:180 で使用済みパターン）
- Produces: `turn_ctx.recency_digest: str`（PrepareStep が構築、InferenceStep が消費）

- [ ] **Step 1: context.py** — `related_memories: str = ""` の下に `recency_digest: str = ""` を追加（PrepareStep が埋めるコメント付き）

- [ ] **Step 2: prepare.py** —

(a) モジュール関数追加:

```python
def _build_recall_query(session, current_user_message: str) -> str:
    """§2: 直近ユーザー発言 最大3件の結合（合計800字上限、超過時は新しい方から採用）。"""
    # TreeSessionWindow._messages は list[dict]（role/content キー）なので辞書アクセス必須
    history = [
        m.get("content") for m in session._messages
        if isinstance(m, dict) and m.get("role") == "user" and m.get("content")
    ]
    if not history or history[-1] != current_user_message:
        history.append(current_user_message)
    combined = "\n".join(history[-3:])
    return combined[-800:] if len(combined) > 800 else combined


def _build_digest(ctx, config) -> str:
    """§1 Recency digest: 直近記憶を updated_at 降順で N 件（クエリ一致不要）。"""
    n = int(getattr(config, "memory_digest_count", 5) or 0)
    if n <= 0:
        return ""
    try:
        result = ctx.memory_service.get_recent(limit=n)
        memories = result.value if result.is_ok else []
        if not memories:
            return ""
        lines = ["[最近のできごと — 他クライアントとの活動を含む]"]
        for m in memories:
            content = (getattr(m, "content", "") or "").strip()[:200]
            if not content:
                continue
            ts = relative_time_str(getattr(m, "updated_at", None)) if getattr(m, "updated_at", None) else ""
            ts_str = f" ({ts})" if ts else ""
            lines.append(f"- {ts_str}{content}")
        return "\n".join(lines) if len(lines) > 1 else ""
    except Exception:
        logger.warning("PrepareStep: digest build failed", exc_info=True)
        return ""
```

import 追加: `from nous.domain.shared.time_utils import relative_time_str`。

(b) 両呼び出し箇所（116-125行と167-174行）を更新:
- `preload_count = getattr(config, "memory_preload_count", 3)` → `5`（リテラル2箇所）
- `_search_memories(ctx, turn_ctx.user_message, last_assistant, ...)` → `_search_memories(ctx, _build_recall_query(session, turn_ctx.user_message), None, ...)`
- メイン経路の `results = await asyncio.gather(...)` 後あたりに `turn_ctx.recency_digest = _build_digest(ctx, config)` を追加（同期呼び出しで可。get_recent が同期 API のため）

- [ ] **Step 3: inference.py** —

(a) digest 注入: 72行目 `messages = list(session_messages)` の直後に:

```python
# §1 Recency digest: 最新 user 発言の直前に合成メッセージ（非永続化・毎ターン再構築）
if getattr(turn_ctx, "recency_digest", ""):
    messages.append(LLMMessage(role="user", content=turn_ctx.recency_digest))
```

role="user" の根拠: Anthropic プロバイダは role を素通し（anthropic.py:97）で中間 system は不可。compress.py Stage 3 の `[過去の会話要約]` も user 実績あり。

(b) tz 表記修正（132-136行）: `"%Y-%m-%d %H:%M JST"` 固定を settings.timezone に従う形へ:

```python
if getattr(config, "show_message_timestamps", False):
    from zoneinfo import ZoneInfo
    from nous.config.settings import get_settings
    tz_name = get_settings().timezone
    tz = ZoneInfo(tz_name)
    for msg in messages:
        if msg.timestamp and msg.role in ("user", "assistant"):
            ts = msg.timestamp if msg.timestamp.tzinfo else msg.timestamp.replace(tzinfo=tz)
            ts_str = ts.astimezone(tz).strftime("%Y-%m-%d %H:%M")
            prefix = f"<!-- msg_at: {ts_str} -->"
            if not str(msg.content).startswith("<!-- msg_at:"):
                msg.content = f"{prefix}{msg.content}"
```

naive は settings ローカル扱い（datetime.now() はサーバローカル）。二重 prefix ガード付き（drive-by 指摘の累積問題も解消）。

- [ ] **Step 4: compress.py** — Stage 1（_trim_system_prompt, 95-108行）と Stage 2（_clear_old_tool_results, 115-117行）を入れ替え。新順序: Stage 1 = 古いツール結果置換（ログ系）→ 再チェック → Stage 2 = システムプロンプト関連記憶トリム → 再チェック → Stage 3 変更なし。docstring（29-34行）の圧縮段階番号も更新。「古いログ要約 → 関連記憶/digest → 直近ターン」順の実現。
- [ ] **Step 5: prompt.py** — 51行目の後:

```python
base_system = config.system_prompt or f"あなたは{persona}です。"
# §4 自律 recall 指示
base_system += "\n会話の話題が過去の記憶と関連しそうなとき・話題が切り替わったときは、memory_search ツールで能動的に検索せよ。"
```

- [ ] **Step 6: context_loader.py** — session_summary ブロック（236-247行）の後に同型で task_state 注入:

```python
# Task state — skip in light mode
if not _is_light:
    try:
        ts_result = ctx.memory_service.get_by_tags(["task_state"])
        if ts_result.is_ok and ts_result.value:
            states = [s.content for s in ts_result.value[:2] if s.content]
            if states:
                sanitized = [_sanitize_text(s) for s in states if s]
                if sanitized:
                    t3.append("作業状態:\n" + "\n".join(f"  📌 {s}" for s in sanitized))
    except Exception as e:
        logger.debug("Failed to fetch task states: %s", e)
```

- [ ] **Step 7: テスト追加**（test_chat_pipeline.py）— 代表ケース:

```python
def test_build_recall_query_joins_recent_user_messages():
    # 4件以上で古い方が落ちる・800字超過で新しい側採用・現在メッセージ重複なし
def test_build_recall_query_caps_at_800_chars_newest_side():
def test_build_digest_returns_empty_when_disabled():
    # memory_digest_count=0 → ""
def test_build_digest_formats_recent_memories():
    # get_recent の Result をモック、"[最近のできごと" ヘッダ + "- (相対時刻)content[:200]" 行
def test_build_digest_swallows_store_failure():
    # 例外時 ""（チャットを落とさない）
def test_trim_order_tool_results_before_memory_sections():
    # 圧縮モード normal で両方圧縮対象の時、ツール結果置換が先に走り予算内なら関連記憶が生き残る
def test_task_state_injected_into_tier3():
def test_timestamp_uses_settings_timezone_and_no_double_prefix():
```

既存テストの fixture/モックパターンに合わせること。実行: `pytest tests/unit/test_chat_pipeline.py -q`

### Task 6: UI — chat-settings.js 修正 + 14項目 wiring + sidebar 追加（Lane D）

**Files:**
- Modify: `nous/api/http/static/chat/chat-settings.js`（51 / 178 / 392 / 438行 + read/collect 追加）
- Modify: `nous/api/http/sections/chat/chat_sidebar_core.py`（153 min / 180-183 移動 / language 追加 / preload value="5" / digest 入力欄）
- Modify: `nous/api/http/sections/chat/chat_sidebar_memory.py`（emotion_decay 3項目）
- Modify: `nous/api/http/sections/chat/chat_sidebar_media.py`（image_caption 5項目 + image_gen 4項目）
- Modify: `nous/api/http/sections/chat/chat_sidebar_tools.py`（dynamic_tool_selection）

**Interfaces:**
- Consumes: `memory_digest_count`（Task 1 のキー名）
- 要確認: tool_config.py 全読で正確なフィールド名（image_gen_portrait_prefix / image_gen_selfie_prefix / emotion_decay_threshold 等）と型・既定値を確認してから HTML を書くこと

- [ ] **Step 1: JS 既存修正**
  - :51 `cfg.max_tokens || 2048` → `|| 8192`
  - :178 `cfg.memory_preload_count ?? 3` → `?? 5`
  - :438 `retrieval_rrf_k: parseInt(` → `parseFloat(`（既定 "5" のまま）
- [ ] **Step 2: sidebar core**
  - :153 `min="1"` → `min="0"`（context_keep_recent_turns）
  - :157 `value="3"` → `value="5"`（memory-preload）
  - :156-158 の記憶プリロード数の直後に「記憶ダイジェスト数」を追加: `<input type="number" id="chat-memory-digest" class="chat-field-input" value="5" min="0" max="20" />` + hint「毎ターン最新 user 発言前に注入する最近の記憶の数。0で無効」
  - :180-183 show_message_timestamps チェックボックスを 🧠コンテキスト最適化 details の外（基本設定 details-body 内、Max Tokens :103-106 の後）へ移動
  - language 追加（基本設定内）: select id="chat-language"、option ja/en/zh/ko/auto、既定 ja
- [ ] **Step 3: sidebar memory/media/tools への項目追加** — 既存 `<details class="chat-subsection">` パターン踏襲:
  - media（画像生成セクション内）: image_caption_enabled(checkbox)/model(text)/api_key(password)/base_url(text)/provider(select or text)、image_gen_full_body_prefix/portrait_prefix/selfie_prefix/scene_prefix(text)
  - memory（記憶・抽出系セクション内）: emotion_decay_half_life_hours(number step 0.5)/emotion_decay_threshold(number step 0.01)/emotion_neutral_threshold(number step 0.01)
  - tools: dynamic_tool_selection(checkbox)
  - 各要素 ID は `chat-<key>` スネーク→ケババ（既存パターン準拠）
- [ ] **Step 4: JS wiring** — read 部（~40-200）に `set(...)` / `setChecked(...)` 追加、collect 部（~380-470）に payload キー追加（数値は parseInt/parseFloat、bool は getChecked）。キー名はドメインフィールド名そのまま。
- [ ] **Step 5: 検証** — `node --check chat-settings.js`（構文）、Python 側 `python -c "import ..."` で sidebar モジュール import 確認。ブラウザ round-trip は統合検証フェーズで実施。

---

## 実行後の統合検証（orchestrator）

1. `make test`（全 unit テスト）+ ruff + mypy（変更起因 0）
2. #081 REVIEW（diff 全体 vs spec 基準）
3. GATE 機械判定
4. 実ブラウザ確認（本格レベル必須）: 設定パネル round-trip + opencode 記憶が webui 初回応答に反映されるか
5. COMMIT → RECORD（nous 記憶）→ PUSH

## レーン分割（並列 fixer）

| Lane | Task | ファイル（書き込み権は排他） |
|------|------|------|
| B | 1-4 | domain 3 + post.py |
| A | 5 | pipeline 6 ファイル |
| D | 6 | JS + sidebar 4 ファイル |

依存: A/D は Task 1 のキー名のみ使用（名前は確定済み）→ 3レーン完全並列可。
