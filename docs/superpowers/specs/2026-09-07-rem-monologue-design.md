# REM 独り言（Monologue）設計書

- 状態: 承認待ち
- 日付: 2026-09-07
- 関連: docs/superpowers/specs/2026-09-06-rem-idle-and-modal-unification-design.md（REM アイドル駆動化の基盤）

## 1. 背景と目的

アイドル駆動 REM（記憶強化）はバックグラウンドで静かに動くが、ユーザーからは存在が見えない。ユーザー要望: 「REM 処理をチャット UI に LLM 発話させてログに残す。独り言として蓄積すれば、20 時間後の再会で『やっと話せたね』を出せるのでは？」

lib-1 調査（先行技術 14 件）の結論:
- sleep-time 処理を発話露出する先行例はゼロ（独自アイデア）
- 都度発話 (A) は通知予算（unsolicited 3〜5 件/日が天井）違反＋「犬の遠吠え」化リスク
- 推奨は (C) 再会時導入: 発話ゼロ・独り言ログ蓄積・再会時に system prompt 注入 → チャット LLM が「やっと話せたね。この間◯◯のこと考えてた」を自然生成
- 注入効果は再会ターン（コンテキストが空に近い瞬間）で最大化。herta では感情・洞察の system prompt 注入が実効あることを SSE 実測で確認済み

ユーザーの懸念「注入ログに引きずられすぎる」への線量管理を設計に組み込む（§4.3）。

## 2. ユーザー決定

| 項目 | 決定 |
|---|---|
| 方式 | (C) 再会時導入＋表示専用思考バブルあり |
| 発話タイミング | unsolicited 発話はゼロ。表示バブルは REM 処理中のみ |
| 独り言の正体 | REM drain バッチ完走時に LLM が 1 回生成（記憶 1 件ごとではない） |
| 保存 | 素朴な assistant メッセージ保存禁止。session_events の新 kind で分離保存 |
| 線量管理 | 注入は再会ターンのみ・参照 1 トピックまで・内容薄ければ沈黙・弱めフレーミング |
| 設定 | 脳シミュレーション設定にトグル（既存パターン踏襲） |

## 3. アーキテクチャ

```
EnrichmentWorker._run_cycle() drain 完了
  → MonologueGenerator.generate(persona, memories[])   (LLM 1 call)
      → session_events 保存 (event_type="brain.monologue", metadata_json)
      → wiring SSE emit (kind="monologue", meta={persona, text})  → 表示バブル
Chat pipeline (再会ターン)
  → PromptBuildStep が <monologue_context> 兄弟タグ注入 (gap 条件＋直近 N 件)
```

新規コンポーネント:
- `nous/infrastructure/llm/monologue_generator.py` — `MonologueGenerator.generate(persona: str, memories: list[Memory]) -> str | None`
- 変更: `enrichment_worker.py`（フック）, `session_event_recorder.py` 不要（直接 insert）, `wiring_events.py`（kind 追加 1 行）, `prompt.py` / `context_loader.py`（注入）, `session_config.py`（キー 1 個）, `chat_sidebar_memory.py` / `chat-settings.js`（トグル）, `chat-memory-panel.js`（JS WIRING_KINDS 1 行）, `chat-send.js`（バブル表示）

## 4. 詳細設計

### 4.1 生成（MonologueGenerator）

- `memory_enricher.py` の `_call_llm(provider, system, user_message) -> tuple[str|None, dict|None]`（:127-152）と同じ stream 消費パターンをミラー。provider 解決は `resolve_brain_config` / `brain_llm_*` チェーンと同一経路（brain_llm_dedicated ON=専用、OFF=chat 流用）。
- system prompt: 「あなたは {persona}。今、誰もいない場所で記憶を整理している。直近で処理した記憶をもとに、一人称の独り言を 1〜3 文で書け。会話ではなく独り言。質問や呼びかけを含めない」＋処理済み記憶の本文（1 件あたり最大 80 字に切り詰め、最大 5 件）を user message へ。
- temperature 0.7 / max_tokens 200。出力はプレーンテキスト（JSON なし）。
- 空文字 / None 返しは呼び出し側でスキップ。**失敗は debug ログで握り、enrichment 本体に影響させない**（enrich_service.py:127 の try/except debug 慣習に準拠）。
- 呼び出しは `_run_async` ブリッジ（enrichment_worker.py:255）経由。usage は debug ログ出力のみ（集計はしない）。

### 4.2 フックと保存

- フック位置: `EnrichmentWorker._run_cycle()`（enrichment_worker.py:84）の drain ループ完走後（:116 の後）。**drain が 0 件なら生成しない**。
- 保存: `SessionEvent(session_id="unknown", persona=self._persona, event_type="brain.monologue", summary=monologue_text, timestamp=now, metadata={"memory_keys": [...], "usage": usage})` を `session_event_repo.insert()` で直接保存（try/except debug 包み）。EventBus 経由は使わない。
- chat 履歴（LLM コンテキスト再注入経路）とは完全分離。「素朴な assistant 保存禁止」を構造的に満たす。
- 注意: activity feed（/api/session-events, session_events.py:55）に brain.monologue が現れるのは許容（正直な活動記録）。UI 側フィルタはしない。

### 4.3 再会時注入（PromptBuildStep）

- 注入タグ: `<monologue_context>...</monologue_context>`（開閉対）— `<conversation_history_summary>` と同じ兄弟方式（compress.py:52-78 `_append_history_summary` の先例）。**`__STATIC_END__`（prompt.py:202）以降の動的領域にのみ置く**。prompt.py の dynamic_parts に追加（`<precedence>`/`<character_adherence>` の前）。タグ対チェックの正規表現スタック検証（test_prompt_adherence.py 方式）に新タグが引っかからないよう、内容に生の `<` を含めない。
- 注入条件（全て満たす時のみ）:
  1. `brain_monologue_enabled` == True
  2. `state.last_conversation_time` からの経過 > 900s — context_loader.py:386 のハードコード値を `REUNION_GAP_SECONDS = 900` として context_loader.py に定数抽出し、prompt.py 側から import して両所で同一値を使う
  3. 独り言エントリのうち **timestamp > last_conversation_time** のものが存在（ギャップ中に生成されたものだけ）
  4. エントリが存在する
- 中身: 「最終会話から {人間可読経過時間}。この間、あなたは独り言として次のように考えていた:」＋直近 3 件（各 1 行、古い順）＋フレーミング指示「再会直後の挨拶で自然に触れてよい。ただし参照は 1 つまで、日記の読み上げをしないこと。ユーザーの入力が再会の挨拶でない場合は触れない」。
- 取得: `session_event_repo.get_by_persona(persona, "brain.monologue", limit=10)` → timestamp フィルタ → 直近 3 件。repo が None の場合は注入しない（ユースケース層で安全側）。
- show_message_timestamps=False で time_context が空になる問題（prepare.py:179-182）を踏まないよう、time_context には乗せず独立タグとする。

### 4.4 表示専用思考バブル（SSE）

- サーバー: `wiring_events.py` の `WIRING_KINDS`（:26）に `"monologue"` を追加。worker が生成成功時に `emit(kind="monologue", source="", target="", meta={"persona": ..., "text": monologue_text})`。
- フロント:
  - `chat-memory-panel.js` の JS 側 `WIRING_KINDS` マップに `"monologue": "独り言"` を追加（pushWiringEvent :690 は未知 kind を弾くため必須）。パネル側は既存レンダで source 空フォールバック表示。
  - `chat-send.js`: `N.Core.connectStream` で wiring エンドポイントへ新規ストリーム（名前衝突回避のため別名、例 `"wiring-chat"`）を張り、kind=="monologue" を受けてチャットログ領域に表示専用バブルを描画。`.chat-monologue-bubble`（💭 斜体・薄色・`--text-secondary`）。**アシスタント div には入れるが履歴には保存されない（DB 保存なし・リロードで消える仕様）**。LLM コンテキストへは到達しない。
  - CSP 準拠: textContent / safeSetHTML(esc) 経由。インライン eval 禁止。
- 既存 `.chat-thinking-bubble`（chat-send.js:553-556）の見た目を流用しつつ class を別にする（thinking は chat stream 専用イベントと紐づくため混線させない）。

### 4.5 設定

- `session_config.py`（:95-114 の brain_* 群）に `brain_monologue_enabled: bool = False` を 1 行追加。
- `chat_sidebar_memory.py` `_render_brain_simulation_section`（:173）に checkbox（id `chat-brain-monologue`）＋ `_BRAIN_HELP` に説明追加。
- `chat-settings.js`: `applyChatConfig`（:317-341）と `saveChatConfig`（:362+）に同キー追加。
- 追加キーはこれだけ（gap 閾値・件数は定数。YAGNI）。

## 5. テスト

- unit: MonologueGenerator（モック LLM・成功/空/失敗・usage ログ）、worker フック（drain 0 件で呼ばれない/保存と emit 成功/失敗握り）、prompt 注入（兄弟タグ・キャッシュ境界動的領域・gap 条件・ギャップ前エントリ除外・disabled 時非注入・repo None 安全側）、config round-trip。
- vitest: WIRING_KINDS JS マップ追加、バブル描画（CSP-safe・履歴非保存）、settings round-trip。
- 実機: REM 発火待ちではなく、テスト用に drain を手動実行できる状態で（brain_enrich_auto_run=true + アイドル 2 分待ち）バブル表示と再会注入を確認。

## 6. スコープ外

- (A) 都度発話 / (B) バッチ発話モード
- プロアクティブな先行送信（Nomi/Replika 型）
- monologue の履歴 UI（読み返し画面）
- wiring WIRING_KINDS の python/JS 単一ソース化（drive-by として棚卸し済み）
- session_events DDL の schema.py 集約（同上）

## 7. リスク

| リスク | 対策 |
|---|---|
| 注入への過剰引きずり | 条件 4 点＋参照 1 トピック制限＋弱めフレーミング＋disabled トグル |
| LLM コスト増 | drain バッチごと 1 call（1 日推定 1〜4 call、最大 ~500 in/200 out） |
| ワーカー安定性 | 全処理 try/except debug、失敗時は静かにスキップ |
| キャッシュ崩壊 | 注入は `__STATIC_END__` 以降のみ（動的領域） |
