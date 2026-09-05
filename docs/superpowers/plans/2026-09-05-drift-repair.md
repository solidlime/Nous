# Drift修理 実施計画

> 方針: 判定の厳しさは変えない・可視化はログのみ・UI不変。発火したときに確実に次ターンへ届け、失敗したらログでわかるようにする。

**Goal:** judge発火時にdrift記憶が確実に保存・注入され、失敗時はwarningログで検知できるようにする。

**Architecture:** LLM出力依存だった3条件（tags・importance・件数）をコード側で強制し、沈黙パスに理由付きwarningを付ける。判定prompt・閾値・注入形式は不変。

**Tech Stack:** Python, pytest, ruff（既存流儀）

## Global Constraints

- 判定基準（prompt・temperature 0.0・violation 4値）は変えない
- UI変更なし（SSE・フロント不変）
- 既存テストの流儀に従う（E402等の既存ruff指摘は対象外）
- 本番DBへの書込は検証でも禁止（一時script・モックのみ）

---

### Task 1: drift factのコード強制

**Files:**
- Modify: `nous/application/chat/memory_extractor.py`（drift付加〜保存箇所。監査参照: `DRIFT_VALID_DAYS=7` 25行、`process(..., drift=...)` 274行付近、空fact・重複skip 283-295行、valid_until付与 298-299行、保存失敗 310-314行）
- Test: `tests/unit/test_character_drift.py` に追加

**Interfaces:**
- Consumes: `_with_drift` 由来の `drift={violation, detail}`（`nous/application/chat/pipeline/post.py:86-96`）
- Produces: 保存factの `tags=["character_drift", 種別]` 確定・`importance` 0.8-0.9確定・`valid_until=+7日` 確定

- [ ] **Step 1: REDテスト追加** — LLMがタグ崩れ（例: `tags=["Character_Drift"]` やタグ欠落）・importance範囲外（例: 0.2 / 9.9）を返しても、保存factが `tags=["character_drift", "<violation>"]`・`importance in [0.8, 0.9]`・`valid_until=+7日` になるテスト。既存 `test_character_drift.py:96-152` の流儀で。
- [ ] **Step 2: 実装** — drift付きfactに対しコードで強制: ①tags正規化（`"character_drift"` 存在保証＋violation種別を lower/strip して1件保証、重複排除）②importance範囲外→0.85に補正 ③その後valid_until=+7日付与（現行条件 `"character_drift" in tags` は正規化後に評価されるため確実に付く）。重複排除（類似度0.85）・空fact skipの挙動は変えない。
- [ ] **Step 3: 検証** — `pytest tests/unit/test_character_drift.py tests/unit/test_memory_llm.py -v` 全PASS、`ruff check` 新規指摘なし。
- [ ] **Step 4: Commit** — `git add` 対象ファイルのみ、`fix(drift): enforce drift tags/importance in code`

### Task 2: 沈黙パスのwarning化（ログのみ）

**Files:**
- Modify: `nous/application/chat/pipeline/post.py`（judge例外 199-203行、memory例外 204-210行）、`nous/application/chat/memory_extractor.py`（空結果・空fact・重複skip 276-295行、保存失敗 310-314行）、`nous/application/chat/pipeline/context_loader.py`（取得失敗 287-288行）
- Test: ログ assertion は既存流儀がなければ追加不要。既存テスト全PASSを条件とする。

**Interfaces:**
- Consumes: Task 1の正規化後コード（skip/失敗箇所は不変）
- Produces: 失敗時に理由付きwarningが出ること（UI・戻り値・SSE不変）

- [ ] **Step 1: 実装** — 以下を `logger.warning`（理由フィールド付き）に引き上げ: judge LLM例外、MemoryLLM例外・空結果、空fact skip、重複skip（類似度つき）、保存失敗（`_saved=False`時）。context_loaderの取得失敗は現行debug→維持、light skipは `info` に（失敗ではないため）。文言は `drift=<reason>` の機械grep可能な形に。
- [ ] **Step 2: 検証** — `pytest tests/unit/test_character_judge.py tests/unit/test_character_drift.py tests/unit/test_memory_llm.py -v` 全PASS、`ruff check` 新規指摘なし。
- [ ] **Step 3: Commit** — `fix(drift): warn on silent drift failures`

### Task 3: 結合テスト恒久化

**Files:**
- Create: `tests/unit/test_character_drift_chain.py`
- 参考: fix-4の一時script `drift_proof.py` のL0-L3（judge→`_with_drift`→保存→`_build_context_section`に「前回の反省」）。本番コード実パス、フェイクはLLM境界・DB境界のみ。

**Interfaces:**
- Consumes: Task 1-2の修正後コード
- Produces: 通し結合の回帰保証

- [ ] **Step 1: テスト作成** — L0-L3を通す結合テスト1件＋タグ崩れ入力でも鎖が完走する1件。既存の単体テストと重複する細部は書かない。
- [ ] **Step 2: RED確認** — 結合テストをTask1前コードでFAILすることの確認はstash等で簡易に（できない場合は省略し報告）。
- [ ] **Step 3: 検証** — 新テスト含め drift/judge/memory全セットPASS、`ruff check` 新規指摘なし。
- [ ] **Step 4: Commit** — `test(drift): lock in end-to-end drift chain`

### Task 4: 最終ゲート

- [ ] **Step 1:** `pytest tests/unit/test_character_drift.py tests/unit/test_character_drift_chain.py tests/unit/test_character_judge.py tests/unit/test_memory_llm.py -v` 全PASS
- [ ] **Step 2:** `ruff check` 対象ファイル（新規指摘なし）
- [ ] **Step 3:** 変更なし・commit不要、結果報告のみ
