# Active Memory 強化: pi フック接続 ＆ LLM 鮮度評価 実装計画

> **For agentic workers:** 各 Task は独立チャンク。Steps は checkbox (`- [ ]`) で追跡。TDD 厳守（RED→GREEN→REFACTOR）。コミットは頻繁に。マイグレーションは不要（`valid_until`/`lifecycle_status` は既存列を流用）。
>
> 背景: pi（モデル側）の auto-memory スキルは「モデルの自律発動」前提のため発動漏れが多い。記憶の取込みを pi 側 extension フック（構造層）から nous サーバーへ明示的に流し、nous 側で LLM 抽出を確定実行する。合わせて「時間経過でまだ有効か／古くなったか」を LLM に自動評価させ、`valid_until`/`lifecycle_status` に反映する。

---

## 0. 現状と接合点（作業前に必読）

### 0.1 会話ターンが記憶になる現行経路（= pi では効いてない）

- chat pipeline のみ: `nous/application/chat/pipeline/post.py:164` で `run_memory_llm(ctx, config, payload, tool_calls_log=…)`。
- `run_memory_llm`（`nous/application/chat/memory_extractor.py:353`）が `_CONTEXT_LLM_PROMPT`（`nous/application/chat/memory_prompts.py:21`）で facts / goals / promises / context_update を抽出、facts は重複スキップ（semantic 類似 ≥0.85）後に `ctx.memory_service.create_memory`。`character_drift` タグ付きは `valid_until = now + 7d`（`DRIFT_VALID_DAYS`、同 :33,:416）。
- **pi の MCP 経由対話（herta persona）は chat pipeline を通らない** → 会話の記録はモデル自身が `memory_create` を呼ぶことに依存＝漏れる。これが本計画の主ターゲット。

### 0.2 期限・鮮度の現行実装

- `Memory` エンティティ（`nous/domain/memory/entities.py`）には bi-temporal フィールド `valid_from` / `valid_until` / `superseded_by`、ライフサイクル `lifecycle_status`（active/archived/…）が既にある。
- 検索側フィルタ済み: `nous/domain/search/engine.py:131` コメント部と `:306-319` —「`lifecycle != tombstoned AND (valid_from IS NULL OR valid_from <= now) AND (valid_until IS NULL OR valid_until > now)`」を `SearchEngine` が適用。
- 機械的忘却: `DecayWorker`（`nous/application/workers/decay_worker.py`、persona 毎起動は `nous/application/use_cases.py:723-749`）が FSRS v6 power-law で `strength` を減衰。`importance_scaled_exponent`（entities.py:64）と感情イージング（`ease = 1/(1+0.5*emotion_intensity)`）。gist キー（consolidated semantic）はスキップ。
- **LLM による鮮度評価（valid_until の自動設定・期限切れ判定）は未実装**。現在 `valid_until` が set されるのは character_drift の 7day のみ。prospective（約束/予定）は `valid_until=NULL` のまま半永続。

### 0.3 pi ↔ nous のイベント経路（既存素材）

- 取込口: `POST /api/events/ingest`（`nous/api/http/routers/events.py:160-320`）。PluginConfig（`nous/config/settings.py:240`、既定 OFF、env `NOUS_PLUGIN__ENABLED` / `NOUS_PLUGIN__API_KEY`）Bearer 認証。受信した event を `session_events` テーブルへ insert＋`events.ingested` を EventBus publish。`session.stopped` 型だけは `_summarize_session_end`（同 :47）で終了サマリを `tags=["session_summary"]` 記憶化。
- events の検索 UI: `GET /api/session-events/{persona}`（`nous/api/http/routers/session_events.py`）。CLI/ダッシュボードは `nous/api/http/routers/events.py:81`。
-.pi 側: `~/.pi/agent/extensions/` に置いた `*.ts` は pi が自動ロード（samples: `tool-observer.ts` fire-and-forget JSONL 追記の実装パターン、`mcp-bridge.ts` の遅延接続パターン）。pi-event は `pi.on("turn_end" | "agent_before_settle" | "session_start" | …)`。**pi-web が PID1 で稼働中のため、pi プロセス再起動はしない。拡張追加・アンインストールはファイル配置だけで可能（next turn から反映、reload 系 コマンドは避けること）。**

### 0.4 収束する仕様（方向性／Goal）

1. **pi のあらゆる対話ターンが、pi の自律判断と無関係に nous へ流れ、nous 側 LLM が抽出・保存する**（= 発動漏れの解消）。
2. **prospective 記憶に LLM が適切な有効期限を付け、期限切れ/化学的陳腐化は LLM が評価して lifecycle を変える**（=「古くなったか」の自動判断）。
3. 既存の FSRS decay・bi-temporal・consolidation は**壊さない**。LLM 評価は「意見を層に足す」方式（機械 decay の代替ではない）。

---

## 1. Architecture

```
pi セッション (herta persona)
  └─ nous-events.ts (pi extension, ~/.pi/agent/extensions/)
       ├─ session_start   → POST turn events: session.started
       ├─ agent_before_settle / turn_end(最終ターン)
       │   → POST: turn.completed {user_text, assistant_text, tool_calls_log}
       ├─ session_before_compact(fire 時) → POST: session.compacting
       └─ session_shutdown → POST: session.stopped
       (全て fire-and-forget。失敗時 stderr ログのみ・例外を投げない)
              │  HTTPS POST /api/events/ingest  (Bearer plugin key)
              ▼
nous server (nas:26262)
  events.py::events_ingest
       ├─ 既存: session_events insert + events.ingested publish
       ├─ [新] hook_pipeline: turn.completed / session.stopped 型を検知したら
       │    fire-and-forget で _run_hook_extraction(ctx, persona, events)
       │    → MemoryLLM(context prompt)再利用で facts/goals/promises/context_update 抽出
       │    → conversation_tool_calls_saved と同様に memory_service 保存
       └─ freshness_worker(新, 24h cycle)
            - 対象: 期限未設定/期限近い prospective & 30日+未アクセス記憶
            - LLM 1 回評価 → verdict: keep / expire / set_validity / demote
            - memory_service.update_memory(key, valid_until=…/lifecycle_status=…)
            - expiry 近い prospective は session_begin 概要欄で優先表示
```

### 1.1 ポイント

- **pi 側は“観測と転送”に徹する**（tool-observer.ts の不変条件相当: 記憶判断・整形は*pi ではしない*）。本文の丸めは nous 側の `_ellipsize` 相当へ委譲。
- **抽出の LLM 呼び出しは nous 側既存の `MemoryLLM` を再利用**（`_CONTEXT_LLM_PROMPT` と `_parse_memory_llm_result`、`memory_extractor.py:187`）。重複スキップ・normalization・facts 一人称規約を流用する。
- **鮮度評価 worker は ConsolidationWorker の thread パターンに倣う**（`nous/main.py:240-245` で `ConsolidationWorker` が module 起動。Dataset 1 つを `_workers` に追加して graceful shutdown に乗せる）。
- LLM 評価は importance 下限（`ForgettingConfig.min_strength` や DecayWorker の strength 値）を**直接書き換えない**。`lifecycle_status` と `valid_until`、必要時 `importance` のみ更新。
- 評価対象は gist（`is_ltm` と gist 関連、consolidated は対象外）で DecayWorker と同じスキップ規約を採用。

---

## 2. CPI Runbook（実装前の現場規約）

- テストコマンド: `uv run pytest tests/unit`（新規 test file は `tests/unit/test_hook_extraction.py` / `tests/unit/test_freshness_worker.py`）。
- pydantic Settings は env prefix `NOUS_`、nested は `__`（例 `NOUS_PLUGIN__ENABLED=true`）。
- Dockerfile/Compose で image:「Nous」→ `docker compose -f docker-compose.yml build nous` がビルド前提。CI は `.github/workflows/ci.yml` に従う。
- docstring 標記・日本語コメント推奨（repo 従来方針完全準拠）。
- Read before write: 実装前に本 plan の接合点クラス・関数名を該当 file で確認。行番号は drift するので body で grep する事。

---

## 3. Task A: pi 側 extension `nous-events.ts`

> **実行環境注意:** pi-web が PID1 で動作中。pi 自身の再起動・reload を伴う検証は禁止。拡張配置はhot-loading 可能（next turn から適用）だが、動かすなら人形（inbox 宛 message）で軽いスモークテスト（例: 「pi 経由でこの memory が流れたか」memory_read で只今確認）を一回行う事。**bun/playwright不要**。node built-in `fetch` のみ。

### 収集する pi events

- `pi.on("session_start", …)`: POST `session.started`（ローカル cwd・session 名など metadata）
- `pi.on("agent_before_settle", …)`: その settle で完了した援助アシスタント最終 turn の user/assistant text、および tool result の短要約（entire raw tool output は載せない、80 字切り😉 `_ellipsize` 相当）を POST `turn.completed`
- `pi.on("session_before_compact", …)`: POST `session.compacting`（summary が飛ぶ前に nous 側で会話記憶は hook 済みが基本だが miss した時のセーフネット）。**※ pi 側 compact hook は summary が入る前に現在コンテキストを取得可能な boundary として使用し、save としてはnous 側 hook 経路と併存可**
- `pi.on("session_end" | "session_shutdown", …)`: POST `session.stopped`

### Payload 形状（確定版）

```jsonc
POST http://nas:26262/api/events/ingest
Authorization: Bearer <NOUS_PLUGIN__API_KEY>
{
  "session_id": "<pi session id or stable uuid>",
  "persona": "herta",
  "events": [
    { "type": "turn.completed",
      "timestamp": "<ISO>",
      "summary": "turn: <user first 40 chars>",
      "detail": {
        "user_text": "...",           // ellipsize 4000 文字
        "assistant_text": "...",      // ellipsize 4000
        "tool_calls_log": [{"tool":"read","args_summary":"a.p:12","ok":true,"ms":31}]
      },
      "metadata": {"kv_keep": "..." } // optional
    }
  ]
}
```

### 実装条件

- ### **Files:**
  - Create: `~/.pi/agent/extensions/nous-events.ts`
  - テスト構築不要（pi 拡張は integration で手動スモーク）。型チェックは pi が TS ロード時に実施するので型ミスは即検知できる。
  - endpoint/key は env `NOUS_HOOK_URL` (default `http://nas:26262/api/events/ingest`)・`NOUS_PLUGIN_API_KEY`（session 側取得 via readFileSync + homedir config or process.env）から取得。secret は**落ち込みない piklok は作らないこと**（tool-observer.ts の salt pattern 同様呼び出し側 marker なし本人確認）。
- 必須条件:
  - [ ] 例外を投げない（全 handler を try/catch）、失敗は `console.error` 1 行で止めない。
  - [ ] turn.completed は turn あたり**最大 1 回**（重複送信で記憶 2 重生成を防ぐ。`agent_before_settle` が複数回叩かれてゆるすように debounce/idempotent id（turn number 等を hashed `event key`）を入れる）
  - [ ] fetch は `AbortSignal.timeout(8000)` 或いは必要 timeout で、fire-and-forget（`.catch(()=>{})`）
  - [ ] tool_calls_log は tool-observer.ts 同様、**args 原文を絶対に流さない**（summary は path/line 数レベルの薄いメタ）。
  - [ ] extension 登録は ファイル drop のみ。AGENTS.md（ユーザー環境メモ）に pi-web `tools:` が builtin 7 に絞られる既知バグがあるので、herta persona の session が全会話を hook にする設定は、**pi-web 側辞書でなく** chezmoi 管理下の人形 profile 直接編集が正道かを確認してから行う事。

---

## 4. Task B: nous 側 hook extraction pipeline（turn.completed 記憶化）

**Files:**
- Modify: `nous/api/http/routers/events.py`
- Create: `nous/application/hooks/memory_extraction.py`（pipeline 依存なし、MemoryLLM 呼出＋実行）
- Test: `tests/unit/test_hook_extraction.py`（新規）

**Interfaces:**
- Consumes: `run_memory_llm` 的要素（`nous/application/chat/memory_extractor.py`）を**そのまま import する必要は無い**。本タスクは ChatConfig 無し・payload 形違い (user/assistant/tool_calls_log) であり、`MemoryLLM.process(config, **common)` を模倣して新規 thin wrapper を作る。再利用率を Max にする為、`_CONTEXT_LLM_PROMPT` は format(*kwargs) で使い回す（改変禁止）。
- 保存先: `nous/domain/memory/service.py::create_memory`（facts）＋ `handle_goal/handle_promise` に相当する登録は memory_extractor.py 自体の process を呼ぶ事で重複共通化する。実装どうしで重複処理を繰り返さない事（Best: `memory_llm.py::run_memory_llm` は split して reusえる範囲を 抜き出す refactor-instructions.md 第1節 note 参照）。**必ずしもそんな refactor は不要**；新規モジュールで「MemoryLLM v2」を薄い copy にする方が安全（既存 pipeline に手を入れる regression リスク < 重複コスト）。

### 詳細処理フロー（概要）

1. `events_ingest` 受けた events の中で `type == "turn.completed"` を検知（複数可、独立に処理）。
2. `hook_extraction.py::run_hook_extraction(ctx, persona, event)` を `asyncio.create_task(...)`＋`_track_background_task` (`nous/domain/memory/service.py:42` pattern) で fire-and-forget。
3. task 中身:
   - payload 組み立て: user_text / assistant_text（tap tool_calls_log 概要）を `_CONTEXT_LLM_PROMPT.format(...)` に渡す（`{context}` は `get_context 的 active 排他` で作る（she no context too long の通常プロンプト導入部束ねは `_build_memory_llm_context`（`memory_extractor.py:221`）の似せ違い）。`commitments` は active commitments と同 refresh 率。})
   - LLM provider は `MemoryEnrichmentConfig`（settings.py:93）と同一の解決経路。
   - `MemoryLLM.process(config, user_message, assistant_response, context=…, commitments=…, mode="context")` → JSON parse は `_parse_memory_llm_result`。
   - facts → 類似 ≥0.85 skip（README の `write_service._check_duplicate` 0.75 threshold とも整合仕様に注意）→ `create_memory(...)` tags corrected、`emotion` neutral normalize。
   - goals/promises → existing active list と照合、create / achieve / cancel。
   - `context_update` → `update_context` 同様 route (memory_service 経由)。
   - 戻り値は logger.info で「hook_extraction: n facts/g/p saved persona=…」と1行。
4. `session.stopped` の `_summarize_session_end` は converter 交換なし。そのままの path 維持（重複で 2 �EXPRを防ぐ為 hook pipeline 扱わない事)。
5. `turn.completed` は **pi からの turn 毎に抽走消耗する**ので、Fatigue is notorious: **LLM call 失敗時は常に no-op（suppress）**。failures は `logger.warning("hook_extraction failed: %s", e)` のみ。pi 側 turn spiked 流れの failure は redis 等ではなく、session_events テーブルに `type=hook_extraction.failed` を insert すれば OK（dashboard 可視化で十分）。

### Tests：`tests/unit/test_hook_extraction.py`

- [ ] `run_hook_extraction` が MemoryLLM の stub で facts 1 件→ `create_memory` が呼ばれその内容が pass する（monkeypatch `MemoryLLM.process`）
- [ ] LLM が空の result で走っても例外が外に漏れず、また memory 作らない
- [ ] 事前に大の内容近い memory が既存であれば skip（重複判定 stub）
- [ ] turn.completed 含む events 列に含まれない時は意味のない node 呼ばれない
- [ ] events 経路で喙形 authentication fail（plugin off, API key fail）で抽走しない（events.pyの既存 tests に既存ある流れ追加）

---

## 5. Task C: LLM 鮮度評価 worker（freshness_worker）

**Files:**
- Create: `nous/application/workers/freshness_worker.py`
- Modify: `nous/main.py`（ConsolidationWorker 同所に worker 起動線を 1 行追加）、`nous/config/settings.py`（`FreshnessConfig` 追加）
- Test: `tests/unit/test_freshness_worker.py`（新規）

**対象選定（SELECT 条件）**:
- `lifecycle_status = "active"`
- ate（下記クエリ）あたり上位 N 件 (batch size default 20/run):
  - **期限切れ近い prospective** : `valid_until IS NOT NULL` かつ `%now 日 ~ +7日目` i.e. 7日以内有効期限: memory の修身
  - **冰箱 prospective** : `valid_until IS NULL` かつ `kind = 'prospective'` かつ `updated_at < now-30d`
  - **30 日未アクセス記憶**: `last_accessed` or `updated_at` が 30 日以上前 (kind 任意、gist/skill keys 除外)
  - importance < 0.8 優先。importance ≥ 0.8 は protected (rating only)。
- お/skip: gist keys、`source_type in ("consolidated")`、`targeted valid_until <= now`（既に expired のもの）

**Timeout / STALE: 24h cycle（ConsolidationWorker follow）。** 1 run 1一回 prompt で 20 件まとめて評価しても寒い（call 総点数は1)。**Batch prompt を用いる**（complex ではなく simple、assertion 規模）。

### Evaluation Prompt（方向性）：の JSON

```json
{
  "verdict": "keep|expire|reschedule|demote",
  "valid_until_suggestion": "<ISO or null>",
  "importance_suggestion": 0.4,
  "reason": "…"
}
```

- `keep`: 何もしない（valid_until = null で即死記憶一本）
- `expire`: `lifecycle_status="archived"` …意図から消える、search も引っかからない
- `reschedule`: `valid_until = suggestion` で scheduled。prospective 用
- `demote`: importance = suggestion（0.3-0.6）に down grade（validity は維持）

### 保存ア prominently

- 書込みは `ctx.memory_service.update_memory(key, valid_until=… / lifecycle_status=… / importance=…)`（`service.py:233`）＋ updated_at auto-update by infra。**必ず適用前の value と verdict reason を session_events (`type=freshness.verdict`) に 1 件 insert** and trace 可視化＋ リセット不可（人間 ops に undo 可能なレポート）。
- `lifecycle_status="archived"` は soft: metadata 上は明白で restore 可能（memory_update で戻せる）。`memory_delete`（tombstone）は**絶対に使用しない**。
- prompt push context: `{persona}` は `get_context` で active commitments 一括（related 引き出し判断用）。`now` は `get_now()`（`nous/domain/shared/time_utils.py`）に統一。

### Tests：`tests/unit/test_freshness_worker.py`

- [ ] SELECT 候補：30日未アクセス記憶 3 件のうち gist /的重要性高位 1 件が除外されること
- [ ] LLM stub verdict=expire → `update_memory(lifecycle_status="archived")` が呼ばれる；valid_until suggestion 空なら Avoid
- [ ] LLM stub verdict=reschedule → valid_until 更新
- [ ] importance >= 0.8 は protect 入口 `/protect` が valid_until suggestion があった場合のみ、理由跡 sensory: Lightでの importance 不要
- [ ] LLM が invalid JSON / timeout / Provider 破の場合 → 1 cycle 全体が exception で落ちて worker loop 内の suppress 継続、memory に無変化
- [ ] session_events insert は verdict 毎に 1 行、failures は `type=freshness.verdict, summary="error: …" `

**Worker wiring:**

- `nous/main.py` `create_app()` で ConsolidationWorker 隣に:

  ```python
  from nous.application.workers.freshness_worker import FreshnessWorker
  fw = FreshnessWorker(settings); fw.start(); _workers.append(fw)
  ```

- graceful shutdown は `_workers` を通して自動（`main.py:263-285` 既存）を利用。

**Settings:**

```python
class FreshnessConfig(BaseModel):
    enabled: bool = True                  # NOUS_FRESHNESS__ENABLED
    interval_seconds: int = 86400
    batch_size: int = 20
    stale_days: int = 30                  # 未アクセス判定
    expiry_probe_days: int = 7            # valid_until 近接評価
    provider: str = "openrouter"          # MemoryEnrichmentConfig と同一形式 provider/base_url/model
    model: str = "openai/gpt-4o-mini"
    base_url: str = "https://openrouter.ai/api/v1"
```

（api key は `MemoryEnrichmentConfig.get_effective_api_key(settings)` の同型 helper 利用可能。**provider/model は `ChatConfig` 頭 / runtime config の`Refresh`** IMplementation note: configDriven provider 責務は既存 pattern を真似る「get_effective_*_api_key」実理）

---

## 6. Task D: session_begin への「期限切れる prospective」先出し

**Files:**
- Modify: `nous/domain/memory/query_service.py`ppi（or `nous/api/mcp/_tools_memory.py`）※実装者は session_begin の memory overview の軽量 **読み出し部** を特定してから着手。この plan では file の該当ハンドラが特定できていない。grep 開始文字列は `session.begin` `session_begin` `PROJECT MEMORIES`=`project:<slug>`。

**条件:**

- session_begin 返信に `【期限が近い予定・約束】` セクションを新設: `kind="prospective"` かつ `valid_until is not null` かつ `valid_within` 7 日以内 → 一覧表示（max5）。ただし **ONE SHOT / lagne prospective ではない**。
- ついで `valid_until` が既に超過している prospective 記憶（expired_but_active 状態）を一覧し「期限切れに見える」と表示。freshness_worker が archiving する前に LLM に「会話に自然に inject される」効果。

**Tests:** `tests/unit/test_pending_freshness_begin.py`（新規）: expired prospective 2 件が先頭に来る・通常 semantic は入らない。

---

## 7. DEPLOY 手順（この環境固有）

nas の Docker compose は **`ghcr.io/solidlime/nous:latest`** イメージ (repository `/d/Code/Nous` docker-compose.yml)。Deploy オプションは 3 つの方式が考えられるが, **このプロジェクトの初期の説明仕様は「compose override で `./nous:/app/nous:ro` を上書き」**（`docker-compose.override.yml`）が dev certo に配置されている。pickle 最低の deploy:

1. **Validation**: ローカルで `pytest tests/unit -q` 好 が pass
2. push GitHub → CI pass（ci.yml 静的 path は本 repo の・ compose は会議必要か!）
3. NAS にて: `git pull` → `docker compose restart nous`（podha local Wassera・build が image 派生を導入した時は `docker compose build nous && docker compose up -d nous`）
4. `/health` で確認。`GET /api/session-events/herta?event_type=turn.completed&limit=5` で pi 側 hook の流れ掛的を観測。
5. Portainer 管理の場合は stack_update (pull_image=true) を介してもよい。

---

## 8. Verification（通したら PASS とみなせる）

- [ ] `uv run pytest tests/unit -q` 全 pass（既存 2465+ unit に regression なし）
- [ ] mypy 差分 0（baseline は不健全の為、**差分比較でのみ判定** — `docs/memory-time-context-2026-09-15.md` の技訓所載）
- [ ] 実環境スモーク:
  - [ ] herta で pi セッションを新規起動（session\uff0eちゃんと pi 拡張が自動 load されて turn 終了後、nous に `turn.completed` が届き、memory_read で新 facts が積まれたなら PASS）
  - [ ] freshness worker 1 回 cycle を warm（手運転 `FreshnessWorker(settings).run_cycle()`）で local、write と session_events が SQL·dashboard 上見える。
  - [ ] `session_begin` の概要に「期限が近い予定・約束」が見えれば D PASS

---

## 9. 風険與教訓（過去 plan からの判明済み事）

- **subagent 疑似死亡**: フックで人形を起動する時、「死んだ」と断定する前に `git status` 差分確認（memory-time-context 記録）
- **quality decay loop 回避**: machine 式 FSRS＋LLM 評価が二重になり効かはつもりが対立すること。**decay_worker の strength 降下を絞らと用とする実装を追加しない**（Strength 減衰は FSRS に任せ、LLM evaluation は lifecycle/importance/valid_until のみ）。*悪化例: LLM が stale と判断した memory も FSRS の strength が「復顆メモリ」として数字が高くなる事に関係性が無い事を防止する valid_from musLine*
- **監査標準**: `_check_duplicate` 0.75 threshold と hook 抽出 0.85 skip の二段階の価値観対立を混同しない（Write系 _check_duplicate は tool 保留、hook 抽出は LLM 出力を事実スキップするしきい値 0.85)。
- **監観方**: LLM 鮮度判定失敗時は「保存しない」（memory_sync で選んだ policy）＋ failed log 残す。
- **pi-web PID1**: pi 詰まり拡張追加はファイル copy load。pi 本体再起動・reload しない。
- **AUDIT**: 规格 QA で memory toward `lifecycle_status="archived"` に到達した記憶 = search 検索は非表示・refresh 作療不能為 *restore 不可を infra コメント上明記する*。

---

## 10. 実行の一度に分割する提案 (実装者が推奨順序)

| Order | Task | 依存 | 作業量 |
|---|---|---|---|
| 1 | Task C freshness_worker (nous) | 無し | 中 |
| 2 | Task B hook extraction (nous) | 無し | 中 |
| 3 | Task A nous-events.ts (pi) | Task B (受信側が無いと転送先無し) | 小 |
| 4 | Task D session_begin 先出し | Task C (情報源が揃う) | 小 |
