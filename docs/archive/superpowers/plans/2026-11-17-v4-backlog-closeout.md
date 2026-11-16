# v4 計画書の未実装項目を閉じる（2026-11-17 / kanban #9–#13）

背景: `docs/archive/superpowers/plans/` の 23 本を照合し、約束されたまま実装が無い
6 件（M1 干渉カウント / M2 due cue の本番発生源 / M4 場所ボーナス / H4+H5 感情強度と
安定度クランプ / C1 compat スイッチ / drift 蓄積）を洗い出して閉じた。

## M1 記憶干渉カウント（2026-09-19-v4-release.md M1）

- `nous/domain/memory/evolution_service.py`: 既存の evolution 検索結果を再利用し、
  `0.85 <= score < 0.95` の既存記憶に `interference_count += 1`。検索回数は増やさない。
  0.95 以上は「同じ記憶の書き直し」側（`memory_extractor.py` の重複スキップは `> 0.85`）。
- `nous/infrastructure/sqlite/memory_crud_repo.py`: `note_interference`。count が 3 に
  達したら `session_events` に `memory.merge_review` を1件（同一ペアの重複防止）。
  新テーブルは作らない。
- 却下: 専用の `interference_review` キュー。`session_events` で足りる。

## M2 due cue の本番発生源（同 M2）

- cue 形式は既に `cue:time:<iso>` / `cue:event:<name>` で実装済みだった。
- `nous/application/workers/prospective_worker.py` を新設。1 時間ごとに全 persona の
  `due_cues` を回し、期限の来た約束キー集合が変わったときだけ `prospective.due` を
  session event に記録する（同じ約束で毎時スパムしない）。
- 注入時は期限切れを除外（`context_loader`）。MCP `get_context` だけは
  `allow_overdue=True` のまま（利用者が明示的に問い合わせる面なので非対称は残す）。

## M4 場所の時間減衰（同 M4）

- 上限クランプ `MAX_INITIAL_STRENGTH = 0.5` を追加（リポジトリが新規エッジを
  `0.5 + strength` で作るため、クランプしないと上限を超える）。
- **既知の穴**: `episodic_place` に書き込み経路が無い（読み取りと schema のみ）。
  場所ボーナスは記憶の `environment` へフォールバックして動かしているが、
  エピソード作成時の場所配線は未了。計画書 `2026-11-12-place-and-body-coupling.md`
  の範囲なのでここでは触らない。

## H4 + H5 感情強度と安定度（同 H4 / H5）

- `nous/domain/search/policy.py`: `emotion_salience_weight = 0.1` を追加し、
  検索合成に `emotion_intensity` を効かせる。`engine._apply_rank_policy` で clamp(0,1)。
- `brain_emotion_gain_k` は削除（`session_config.py` / `query_service.py` / 焼き込み JS）。
- `decay_worker` は commit `1cc15cff` で既に削除済みだったので、H5 のクランプは
  マイグレーション **v13**（`stability > 1.0 AND COALESCE(is_ltm,0)=0 → 1.0`）に移設。
- `emotion_peak` 列は書き込み・参照ゼロなので `-- 廃止:` コメントのみ。DROP は v5。
- 感情伝播は作成時スナップショットのみで既に正しかった（`boost_on_recall` 0 件）。

## C1 compat スイッチ（同 C1）

- `nous/api/http/compat.py`: `legacy_requested()` + 封筒ヘルパ。`compat=legacy` の
  厳密一致のみで旧形を返し、1 行 WARNING を出す。
- `POST /api/session/{persona}/begin` を HTTP に追加（MCP と同じ本体、封筒が既定）。
  失敗時は `compat=legacy` でも封筒（`500` / `{ok:false, data:null, error:{code}}`）。
  旧形には失敗の形が存在しない（旧コードは `DomainError` を `JSONResponse` に渡して
  落ちていた）ため、互換の義務は「成功時の形」まで。
- MCP `memory_search` で profile 未指定・個別重み指定のとき WARNING。
- **見送り**: 既存 HTTP 全ルータの封筒既定化。3 つの JS コンシューマ + 既存テスト
  約 10 箇所 + UI 実機検証が要る。v5 の作業として残す。

## drift 蓄積の配線（キャラクターシミュレート）

- 原因: commit `9d9e7305` で `_with_drift` が消え、`judge_character` の判定が
  `run_memory_llm` の payload に載らないままだった（受け手は全部残っていた）。
- `nous/application/chat/pipeline/context.py`: `ChatTurnContext.drift` を追加。
- `nous/application/chat/pipeline/repair.py`: 初回 judgement が none 以外なら
  `drift` を格納して return（違反の型 + 内訳）。
- `nous/application/chat/pipeline/post.py`: payload に `drift` を載せる。
- これで `memory_extractor._normalize_drift_fact`（tags `character_drift`、
  importance 0.8–0.9）→ `valid_until = now + DRIFT_VALID_DAYS` →
  `context_loader` の「前回の反省」注入、が繋がる。
