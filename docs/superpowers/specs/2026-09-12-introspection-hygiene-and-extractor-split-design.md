# 内省衛生と抽出LLM分割 設計 (2026-09-12)

ステータス: 承認待ち（ユーザー設計フィードバック反映済み・#081 審査 BLOCK 指摘 4 点を織り込み済み）

## 背景・要望（ユーザーからの指摘）

1. アイテムとコンテキストを別LLMで管理（**決定: 抽出LLMを2分割**、チャット中の即時 tool call は残す）
2. 欲(desire)パラメーター導入 → **本設計では中断**（ユーザー決定「欲スロットは今はいいや。中断」）
3. 内省時に感情・身体状態も更新されているか → **更新されている**（正常、introspection.py:621-719 `_apply_result`）
4. リサーチが狙ったデータを取れない。独り言は満足 → 独り言LLMとリサーチLLMは別枠で、リサーチ結果は独り言に還元されない
5. 内省時のツールコールがチャットログに流れない → 実機確認+修正
6. 内省プロンプトの構成確認＋設定可能化
7. 内省が 1h 設定で 2h に 1 回しか発火しない
8. 内省がユーザー対話時刻を更新してしまい、減衰・「○○前に会話」が壊れる
9. デフォルト設定見直し: 裏で回る LLM は全部 1 時間周期、**それ以外は人間らしさの最適値を探す**

## 現状の調査結果

- **内省プロンプト**: `_SPONTANEOUS_PROMPT`（nous/application/chat/introspection.py:79-106）= persona名 + current_state + 最近記憶10件（80字cap, L176/201）+ persona_identity = **system_prompt 先頭2000字のみ**（L591, L202-207）。`system=""` 固定（L230-235）。→ system_prompt の後続部分・一人称ルールが落ちる。
- **LLM呼び出し分離**: 独り言 `generate_spontaneous`（L193-215）→ その後に `_run_curiosity_exploration`（L602-606）: `_select_tool`（L814-851, ワンショット・独り言文脈は curiosity のみ）→ `MCPClientPool.call_tool` 直叩き（L798-799, **event_bus 経由で tool.called が publish されない**。通常経路は `_tools_helpers.py:90-103` `emit_tool_called`）→ `_summarize_and_record`（L861-904, 別記憶+別monologueバブル、**永続化なし→リロードで消失**）。
- **対話時刻の汚染経路（3系統）**:
  1. `nous/infrastructure/sqlite/persona_repo.py:327-341` `_resolve_last_conversation_time` — `max(全記憶のMAX(updated_at,created_at), stored)` を返す。内省が作る記憶（独り言 L708-718 / 反省 L667-678 / 探索要約 L884-890）で押し上げられ、感情減衰（emotion_decay.py:160-165）・身体減衰（body_decay.py:77-82）の時計がリセットされる。
  2. `nous/api/mcp/_tools_persona.py:247`（update_context）と `:88`（get_context）の `record_conversation_time`。curiosity は `disabled_tools` フィルタのみで**任意のMCPツールを実行可能**（introspection.py:784-791）。
  3. `session_event_repo.py:118-126` `last_activity_at` = 全 event_type の MAX(timestamp)。recorder は tool.called/chat.*/session.*/events.ingested（session_event_recorder.py:28-35）、brain.* は直接挿入（introspection.py:682-691,722-745）。
- **発火周期**: enrichment_worker.py:142-152 — interval クロックが `MAX(brain.introspection, brain.introspection_spontaneous)`。ターン駆動内省イベントでもリセットされる → **1h設定が2h化する機序がコード上で確定**（spontaneous 直後にターン内省が brain.introspection を書くと次回が+1h後退）。失敗時（result=None）もイベント記録でクロックを消費（L616-618）。
- **抽出**: `nous/application/chat/memory_extractor.py` `run_memory_llm` L301。`_MEMORY_LLM_PROMPT`（memory_prompts.py:15-101）1回のLLM呼び出しで facts/goals/promises/context_update/inventory_update を抽出。context_update 適用 L484-555（感情・身体・mental/physical・環境・user_info）、inventory_update 適用 L557-594。文脈ビルダー `_build_memory_llm_context` L183-241。
- **フロント**: tool.called の描画先は Activity ページのみ（static/features/activity.js:24,33）。チャットログの tool_call 表示はメイン対話 content_parts 専用（chat-send.js:662-670）。
- **専用LLM設定の既存パターン**: brain_llm_dedicated/provider/model/base_url/api_key（session_config.py:126-130）。プロンプト設定可能の既存パターン: memory_enrichment_prompt_template（session_config.py:91）。

## 設計

### A. 内省汚染の根絶（バグ8の本丸）

| # | 修正 | 内容 |
|---|------|------|
| A1 | 🔴 resolver | persona_repo.py:327-341 — **stored を正とする**。memories フォールバックは stored が NULL の場合のみ（レガシー行救済は維持）。これが全減衰の前提 |
| A2 | 🟠 record一本化 | _tools_persona.py:247 の `record_conversation_time` を削除。post.py:141（ターン終了、try/except 済み post.py:139-143）に一本化。L88（get_context）は外部クライアント互換のため残す |
| A3 | 🟠 allowlist | curiosity のツールカタログを **read-only allowlist** に制限（状態変更系・item_*・get_context（L88副作用あり）を除外） |
| A4 | 🟠 last_activity | last_activity_at を `chat.message` + `chat.llm_response`（service.py:190-198,348-351 ターン完了記録）のみに。tool.called / brain.* / session.* / events.ingested は除外 |
| A5 | 🟡 失敗時クロック | result=None 時は brain.introspection_spontaneous を記録しない（成功時のみクロック消費） |

### B. 発火周期修正（バグ7）

- enrichment_worker.py:142-152 のクロック対象を `brain.introspection_spontaneous` のみに変更。
- **実機確認（修正前）**: session_events の brain.* 時系列をダンプし、2h機序を実際のデータで特定して記録する。
- デフォルト `brain_spontaneous_interval_hours`: 6 → **1**（int clamp 1..72 で表現可）。

### C. ツールコールのチャットログ表示（バグ5）

- curiosity 探索で `tool.called` を event_bus に publish（既存 emit_tool_called 形式踏襲、source=introspection）。
- 探索要約を brain.monologue の既存永続パス（L682-691）に乗せて**リロード後も残す**（新イベント種別は作らない）。
- チャットログへの表示は Playwright 実機確認の上でフロントハンドラ追加（console errors 0 まで）。

### D. 内省プロンプト設定化（要望6）

- session_config.py に `brain_spontaneous_prompt` / `brain_introspection_prompt`（str、空文字=デフォルト使用）を追加。config.json / 設定UI から変更可。
- introspection.py 側は getattr で読み、非空なら `_SPONTANEOUS_PROMPT` / `_INTROSPECTION_PROMPT` を置換。プレースホルダ互換維持（{persona}/{current_state}/{memory_texts}/{persona_identity}）。
- デフォルト改善: persona_identity を system_prompt[:2000] → **全文**（安全弁として上限値を設ける）。**一人称遵守ブロックは注入しない**（ユーザー決定: プロンプトに含まれていれば十分）。

### E. 欲スロット — 中断

ユーザー決定により本設計から除外。将来の拡張として #081 審査で得た設計メモ（固定4スロット・context_state KV JSON・半減期 探索2h/休息6h/関係12h/達成24h・単一書き手）は本specに残すが実装しない。

### F. 抽出LLM 2分割（要望1）

- MemoryLLM の1呼び出しを2つに分割:
  - **context抽出LLM**: facts/goals/promises + context_update（**感情・身体（fatigue/warmth/arousal/heart_rate/pain）・mental/physical state・環境・user_info を担域に明示**）
  - **item抽出LLM**: inventory_update のみ
- 逐次実行（post.py:151 DoneSSE 送出後に回るため体感遅延なし）。並列化はしない（必要時のみ asyncio.gather）。
- **更新除外ルール**（ユーザー決定）: 同一ターン内でメインLLMが update_context tool call で更新したフィールドは、抽出LLMの適用から除外する。item_* ツールが呼ばれたターンは inventory_update を skip。実装: 推論ステップで tool call の適用フィールドを turn コンテキストに記録し、post が除外リストを `run_memory_llm` に渡す。
- 専用モデル設定: `item_llm_dedicated` / `item_llm_provider` / `item_llm_model` / `item_llm_base_url` / `item_llm_api_key`（brain_llm_* 踏襲）。context側は既存 `extract_model` 流用。
- `_build_memory_llm_context`（L183-241）を両LLMで再利用。
- 抽出用プロンプトはコード定数を分割（_MEMORY_LLM_PROMPT → context用/item用）。

### G. リサーチ改善（要望4）

- introspection.py:176,201 の80字capから **exploration タグ記憶を免除**（500字の探索要約が次回内省の入力に届く——リサーチ継続性の構造的修復）。
- `_summarize_and_record` に独り言の curiosity 質問を注入（_select_tool L822 は既存）。
- 要約LLMに構造化出力（満足判定+未解決質問）を持たせ、「狙ったデータが得られなかった」質問を exploration 記憶として次周期に持ち越す。**絞り込みループは導入しない**（1h周期のコスト判断）。

### H. デフォルト値（要望9）

**LLM呼び出し関連のみ 1h。それ以外は人間らしさ最適値。**

| 設定 | 現在 | 提案 | 根拠 |
|---|---|---|---|
| brain_spontaneous_interval_hours | 6 | **1** | LLM周期。B修正とセット |
| reflection_min_interval_hours | 1.0 | 維持 | 既に1h（LLM） |
| brain_enrich_interval_seconds | 60 | 維持 | tick であり LLM ではない |
| brain_idle_after_seconds | 120 | 維持 | drain と共有ゲート。分離は YAGNI |
| forgetting_decay_interval_seconds | 86400 | **3600** | 非LLM。減衰適用の平滑化（実装確認の上で決定: 経過時間依存の減衰計算なら sweep 間隔は平滑性のみに影響） |
| emotion 半減期 | ハードコード | 維持 | 文献校正済み（emotion_decay.py:18-28） |
| body 半減期 | ハードコード | 維持 | 同上（body_decay.py:22-28） |
| novelty 閾値 (0.75/0.6/2.0) | — | 維持 | 苦情なし・LLM非依存 |
| brain_monologue_enabled | False | **True** | デフォルトで独り言あり（人間らしさ） |
| brain_spontaneous_enabled | False | **True** | 同上（1h周期とセット） |

注: デフォルト変更は既存 config.json を持つ persona には影響しない（実効値は config.json が正）。

## 実機検証要件

1. B: 修正前に session_events の brain.* イベント時系列をダンプして2h機序を特定
2. C: Playwright でチャット画面を確認 — monologue バブル表示、リロード後の復元、console errors 0（SSE多用ページなので networkidle 待ち禁止・domcontentloaded+要素待ち）
3. A: 修正後に内省を発火させ、対話時刻・last_activity が動かないこと・減衰時計が維持されることを確認

## テスト方針

- unit: resolver（stored 正/NULL 時 fallback）、last_activity フィルタ、curiosity allowlist、抽出2分割+除外ルール、exploration cap 免除、失敗時クロック不消費、設定フィールド（デフォルト・clamp）
- 既存 full unit suite 回帰（最新 2258+ passed を基準に）

## リスク

- 1h化による LLM/Qdrant 負荷増。多 persona 時は発火位相の分散を検討（今回は単 persona 運用のため対応しない）
- record_conversation_time 削除後の対話時刻は post.py ターン終了依存。クライアント切断で skip され得るが次ターンで回復（#081 評価: 低リスク）
- 抽出2分割で入力プロンプト重複 → コスト約2倍（extract_max_tokens 512 の範囲で許容）
- 実機確認未実施の2点（2h機序の実データ特定、フロント描画）は実装中に必須で実施
