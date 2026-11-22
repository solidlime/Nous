# 履歴ポリシー再設計（永続基線）+ プロンプト再構成（静的拡大・揮発後方退避）+ サンプリング内部化

> **ステータス: 完了・本番適用済** (2026-11-22)。実装: 70a666a7 (Stage 0 削除・履歴 append-only 化・サンプリング設定撤去) + c8aa6c9b (top_p 輸送層完全撤去) + 3d8aa2dc/#011 (静的領域拡大)。Oracle PASS (m04545)。デプロイ: Portainer stack nous (bf31670a〜c8aa6c9b)。実機測定: system プロンプト 2 ターン md5 一致（バイト不変）・cached_tokens 8192/15929 tok (51%) を本番 done イベントで観測。残る 50% 交替ロスは core-coding-pool 2 デプロイメント・ラウンドロビン起因（opencode_go と goat の各 deepseek-v4.1-flash）— 専用エイリアスへの pin は未実施（litellm 再起動が必要なため別判断）。
>
> **追記 (2026-11-22T10:00Z): 上流キャッシュ TTL 実測で pin 不要と確定。** commandcode 側 deepseek-v4.1-flash で同一接頭辞 8,704/8,854 tok が 2/5/10/15 分後も全保持（~20分 gap で消滅、x-litellm-model-name ヘッダで上流識別しつつプール経由で計測）。通常の会話ペース（1〜5分/ターン）なら交互振りでも各上流の鮮度は TTL 内に収まり期待命中率 80〜90% — sticky 化の上乗せ僅か。加えて計測中に opencode 側 deepseek が不調となりトラフィックが影響ゼロで commandcode 側へ全振りしたことで、プール構成のままの2社フェイルオーバーが実証済み。**判定: ラウンドロビン維持（ユーザー指示 m05035「フェイルオーバーは維持したい」）。** 観測は done イベント usage の cached_tokens で継続。wiki: project-nous-chat-latency にも同一内容を記録済み。

v2.1 (2026-11-22) — ルアン・メェイ再判断 (m04513 BLOCK) の指摘 #1〜#10 を反映。v2 からの追加変更:
6. `max_stored_messages` 既定は 200 だった（compression_config.py:14、apply.js:223 の UI 既定も 200）→ 既定 1000 に引き上げ + cap evict と予算 evict の帰着先を分離宣言（両方 history_summary に合流させず、cap evict は従来通り記憶側のみ）。
7. `dynamic_temperature`/`emotion_temperature_scale` 削除の破壊半径を対象リストに追加（service.py:323-346 の EmotionDrivenSampler ブロック・:428 の effective_temp 引数・inference.py:64/96・nous/domain/sampling.py・test_sampling.py・test_chat_service.py:615-627・test_chat_pipeline.py:750-814）。
8. フォールバック文面を修正（要約未保存でも真となる文に）。
9. Stage 2 は削除（トリム移設ではなく）。予算情報は CompressStep 時点でしか存在しないため、逃し弁は Stage 3' に一本化。
10. force_compress 削除・node→LLMMessage 展開の一行仕様・予算合計に揮発ブロックと最新 user を含める・frontend 実在ファイル名の是正・worker への波及と DB ペイロード試算を追記。
1. Stage 3' をエフェメラル再計算から**セッション永続基線（window evict + history_summary 永続化）**へ再設計（指摘 #1/#4/#7）。
2. **Part B を追加**: 動的領域の会話後方退避。v1 では「圧縮はキャッシュ境界を守っていて正しい」としたが、これは機構の話で、実際の静的領域は `base_system` のみ（prompt.py:250）— プロフィール・スキル一覧・PRECEDENCE・ADHERENCE まで毎ターン再構築の動的領域にある（prompt.py:266-365）。**本番のキャッシュ被覆はほぼゼロ**。Stage 0 削除だけでは目的1は数字に出ない（指摘 #2）。
3. service.py:375-390 第2切り詰め経路を対象に追加（指摘 #3）。
4. フォールバック・artifact refs 配線・要約入力上限を仕様化（指摘 #4/#5/#6）。
5. top_p の pop を廃止（pydantic extra=ignore で自動無視 — 指摘 #8）。frontend 4 テストファイルを対象に追加（指摘 #9）。

## 確定した事実（全て本セッションで実測・実読）

- ゲートウェイ経由 deepseek-v4.1-flash: 静的接頭辞 23,808 tok 再送で cached 23,552 (99%)。キャッシュは効く。効いていないのは**こちらの並べ方**。
- `prompt.py:250` static_parts = `[base_system]` のみ。profile/them/tool guidelines/active_skills/time_context/emotion/retrieved_data/PRECEDENCE/ADHERENCE は全て `__STATIC_END__` 以降（動的）。
- `cache_utils.py:23` は単一 system メッセージ `[static+cache_control, dynamic]` → 動的部が会話の前にあるため、**会話部分は一度もプレフィックスキャッシュに乗らない**。
- 圧縮はエフェメラル: `CompressStep.run` の結果は推論に渡るのみ。`TreeSessionWindow` は全 node を SQLite `chat_sessions` に永続化（tree_session.py:240-275、add 毎に upsert）。予算超過レジームでは毎ターン全窓から切込位置を再計算 = Stage 0 と同じ病巣 + 毎ターン LLM 要約呼び出し。
- `TreeSessionWindow._evict_oldest(count)`（tree_session.py:240 付近）: active path 先頭から node を pop、root_id 再指定、`_persist()`、evict_callback 発火。**永続的**な削除。rollback は active_leaf_id 変更のみで非破壊だが、evict 済み node は戻らない。
- `post.py:146-153` が evict_callback → `summarize_and_store`（application/chat/summarizer.py:32, 記憶に保存）を既に配線済み。
- `service.py:287` で window 生成時 `max_messages=config.max_stored_messages` を渡す — service.py:375-390 の第2切り詰め経路（max_stored_messages スライス+`_build_truncation_highlights`）は window 自身の evict と二重管理。
- `_summarize_old_turns`（summarizer.py:60-120）: user/assistant のみ・500字/件、**件数上限なし**・refs 受け口なし・provider 未構成/LLM失敗で None（→ 現状は「何も注入されない沈黙の健忘」）。
- `_collect_artifact_refs`（trimmer.py:200 付近）の呼び出し元は `_truncate_old_messages` 内のみ = Stage 0 削除でデッドコード化。
- `inference.py:289` recency_digest: 最新 user 直前に合成 user メッセージを差し込む先行パターン（非永続・毎ターン再構築）。
- ChatConfig は pydantic 既定 extra=ignore（model_config 上書きなし）。`_distribute_flat_fields`（chat_config.py:110, mode=before validator）が flat/nested 両形態を受け、**全構築経路（config.json・SQLite移行・API）の単一チョークポイント**。
- 診断の静的エラー2件は古いキャッシュの残骸（本セッションで解決済み・mypy クリーン）。ゲートで消失を確認する。

## 設計

### Part A: 履歴ポリシー — 予算駆動の永続基線

**A1. Stage 0（固定窓）削除**
- compress.py から固定窓切り詰めを削除。`_truncate_old_messages` の固定窓用途も削除。turn-boundary カット計算（`_adjust_slice_start` 相当の tool ペア不破壊境界探索）は Stage 3' 用ヘルパーとして残す。
- `_build_truncation_highlights` 削除。
- service.py:375-390 第2切り詰め経路（max_stored_messages スライス+ハイライト注入）を**経路ごと削除**。force_compress（compress.py:115-116、展開 LLMMessage 数で max_stored_messages と比較）も削除 — 展開数と node 数の単位不一致があり、予算駆動化後は無意味。
- `context_keep_recent_turns` 設定キー削除（CompressionConfig から）。保存済み JSON は extra=ignore で自動無視。
- **max_stored_messages 既定 200 → 1000**（compression_config.py:14、apply.js:223 の UI 既定も同値に変更）。理由: 既定 200 のままでは軽い会話（200 node ≈ 100 ターン ≈ 25〜45K tok）で `add()` 内 cap evict が予算駆動（102K）より先に発火し、固定窓が主経路のままになる。引き上げ後は予算 evict（Stage 3'・history_summary に統合）が主経路、cap evict は安全弁に戻る。
  - **2つの evict の帰着先（分離宣言）**: cap evict（`add()` 内・evict_callback→post.py→`summarize_and_store`）は従来通り**記憶側のみ**（memory_search で補完）に流し、history_summary には統合しない。Stage 3' 予算 evict のみ history_summary に載る。二重要約を避けるため。
  - **波及**: proactive/prospective worker は `speak_to_main(..., max_messages=config.max_stored_messages)`（announce.py:46-54）で main セッション窓上限として使用 — 引き上げで「main に保持する worker 発言履歴が増える」だけで機能破壊なし。保存済み config.json の旧値（200 等）は既定変更の対象外でそのまま残る（明示的に設定を更新しない限り）。
  - **DB ペイロード試算**: 実測ベースで node 1件 ≈ 250B。1000 node ≈ 250KB JSON を `add()` 毎に upsert（dump+write）。シリアライズ 1〜2ms・SQLite write 250KB — ターン頻度（低頻度）を考え許容範囲。

**A2. Stage 3'（予算超過時）: 永続 evict + 差分要約**
- 前提: Stage 順序は **Stage 1（古い tool 結果のステータス化）→ Stage 3'** に短縮（Stage 2 は削除・Part B 参照）。Stage 1 で予算内に収まれば無操作。
- Stage 3' 発火時: **node 単位で計算**（`session.get_active_path()` の node 列。LLMMessage への展開は segments で多対多になるため切込は node 界面で行う）。先頭から、**user ノード直前の tool 完了境界**（= assistant(tool_calls)→tool ペアの外）で切込点を決め、予算内に収まるまで繰り返す。evict 後は `get_labeled_messages()` を再生成して次段へ渡す。
- 切込点が決まったら、その node 数分を **window から evict**（`TreeSessionWindow` に公開メソッド追加: 既存 `_evict_oldest`（node 単位・230行）を薄く wrap した `evict_path_head(count) -> list[dict]`。evict_callback は発火させない — post.py の window 上限用と二重になるため）。
- evict した切片の処理（**node（dict）は `_expand_segments` で LLMMessage 展開してから** `_summarize_old_turns` / `_collect_artifact_refs` に渡す。refs の正規表現は展開後の tool content にしかマッチしないため、展開しないと refs は静かに空振りする）:
  - `_summarize_old_turns` を差分要約として使用。入力は evict 切片のみ（ naturally bounded）+ 安全のため件数上限 60 件（超過分は末尾から60件）。**artifact refs を配線**: `_collect_artifact_refs(removed)` の結果を要約プロンプト末尾に「削除済み会話が参照していた添付: ...」として追記。
  - 成功時: 既存 `history_summary`（window payload の新フィールド、後述）に差分要約を連結（`old + "\n---\n" + delta`、全体 4000 字上限、溢れたら古い方から削る）。
  - 失敗/未設定時: **決定論的フォールバック** — 「これより前の会話 N 件はトークン予算超過により省略されています。必要なら memory_search で過去の発言を検索してください。」+ artifact refs（上限 20）。（Stage 3' evict は callback 不発火設計のため記憶側にも保存されていない — 「要約は記憶として保存済み」は失敗時に偽になるため使わない。）
- **history_summary の永続化**: `_persist()` の payload dict に `history_summary: str` を追加（chat_sessions の既存 JSON カラム内。スキーマ変更不要）。ロード側（`cls._from_payload` 相当）で復元。
- 注入: `<conversation_history_summary>` タグで **Part B の [NOUS CONTEXT] 揮発ブロック内**に（タグ名は既存のものを踏襲し、セッション中は構造安定）。
- **予算合計の測定対象**: 会話ノード（展開後）に加えて、揮発ブロック（turn_ctx.volatile_context — アクティブスキル本文・related_memories・history_summary で数K tok）と最新 user メッセージを含めて予算判定する。Part B で揮発が会話後方に移るため、除外すると実際の送信サイズとズレる。
- **切込ループの終了条件**（仕様として明示）:
  - 予算内に収まったら停止。
  - active path 先頭に user 境界が存在しない（先頭が assistant で user が以降にも無い = 単発 REM セッション等）→ **切らない**（無操作）+ 警告ログ。
  - 単一メッセージが予算全体を超える（巨大ペースト）→ そのメッセージは切込対象外。以降は最善努力（残したまま送信）+ 警告ログ。
  - 予算計算は既存の近似トークン見積もりロジックを踏襲（新規推論実装しない）。

### Part B: プロンプト再構成 — 静的拡大 + 揮発後方退避

- **静的領域（キャッシュ対象、バイト不変）**: base_system + プロフィールブロック（me/user）+ TOOL_USAGE_GUIDELINES（スキル一覧込み）+ PRECEDENCE_BLOCK + CHARACTER_ADHERENCE_BLOCK。マーカー `__STATIC_END__` は静的末尾に維持。
  - プロフィール・スキル一覧は persona 設定変更時にのみ変わる（= 設定編集でキャッシュ基線を作り直す。稀で許容）。スキル本文のロードは毎ターン実行のまま（キャッシュは送信側の問題であり、ロードコストは別件 — 変更しない）。
- **揮発ブロック（毎ターン、会話の後方へ）**: them / time_context / 感情 if-then 行 / retrieved_data（current_state + related_memories）/ active_skills / history_summary → 全て **[NOUS CONTEXT]** 合成 user メッセージに統合し、**最新 user メッセージの直前**に注入。recency_digest はこのメッセージに統合（先行パターン inference.py:289 と同一スロット）。
  - 実装: prompt.py は `turn_ctx.system_prompt`（静的のみ）と `turn_ctx.volatile_context`（揮発ブロック文字列）を別々に設定。inference `_build_initial_messages` が recency_digest と volatile_context を統合した合成メッセージを組み立て。
- **cache_utils.build_openai_system_messages**: 動的部が空でも（= marker 以降が空でも）content-parts 形式 `[static + cache_control]` で送る。文字列単一形式は marker 不在時のみ。
- **Stage 2（`_trim_system_prompt`）は削除**（トリムの移設ではなく）。理由: 予算情報は CompressStep 時点でしか存在せず、prepare 時点での常時トリムは品質回帰になる。逃し弁は Stage 3'（予算 evict）に一本化。related_memories が肥大化するのは記憶検索側の返却制御の問題であり、本計画では扱わない。
- **プロンプト意味論の変化**（明示）: モデルは会話を読んだ後に現在状態・関連記憶・感情行を読む順になる。pi 側 nous-inject.ts の「コア section バイト不変 + 変動値は末尾 [NOUS STATE]」方式（2026-10-18 実績）と同じ構造。
- `<retrieved_data>` ガード（RETRIEVED_DATA_GUARD）は揮発ブロック内に維持。

### Part C: サンプリング設定の内部化

- **top_p**: ProviderConfig からフィールド削除 + inference.py:140 の送信削除。`llm/base.py:86` プロトコル引数は既定 None のまま残置（最小差分）。保存済み JSON の top_p は extra=ignore で自動無視、save() の model_dump から自然消滅。**pop 不要**。
- **dynamic_temperature / emotion_temperature_scale も削除**（温度を内部固定とする方針と矛盾するため。プロンプト側の感情 if-then 行は維持）。**破壊半径（削除必須のセット）**: service.py:323-346 の EmotionDrivenSampler ブロック（compute+effective_temp）、service.py:428 の `effective_temp=` 引数、inference.py:64 の `effective_temp` 仮引数、inference.py:96 の解決行（`config.temperature` を直接読む形に）、`nous/domain/sampling.py`（EmotionDrivenSampler の唯一の消費先が消えるためファイルごと削除）、tests/unit/test_sampling.py、test_chat_service.py:615-627・test_chat_pipeline.py:750-814 の前提更新。
- **temperature / max_tokens**: フィールドは残す（内部既定 0.7 / 8192 が常に優先）。`_distribute_flat_fields`（chat_config.py:110）の頭で flat/nested 両形態から temperature/max_tokens を pop — 保存済み値が内部既定を上書きする経路を全構築経路で塞ぐ単一チョークポイント。pop 後は `config.temperature` が常に既定 0.7 を返すため、既存の読み取り箇所（inference・脳継承・サマライザの固定値 0.0 は別物で不変）はそのまま動く。
- **API/UI**: chat_management.py の設定 allowlist から top_p/temperature/max_tokens/dynamic_temperature/emotion_temperature_scale/context_keep_recent_turns を除外（PUT で 400 にするか無視するかは allowlist の既存挙動に従う）。settings UI から該当項目を削除。
- **frontend 実在ファイル**（settings/ 配下は apply.js / apply-groups.js / reset.js / save.js のみ — load.js/tiers.js は存在しない、v2 記載は誤り）: 配線は apply.js:91-97,141,223,240-241・reset.js:33-48・save.js:48-86。テスト更新範囲は top_p 4件（chat-settings-brain.test.js:302-320 / chat-settings-reset.test.js:19,259-278 / chat-settings-save.test.js:103 / chat-settings-tiers.test.js:22）に加え、temperature/max_tokens/keep_recent 前提: reset.test.js:18-48・save.test.js:99-101・brain.test.js:18。
- 掃除: chat_config.py:311 の nullable set 残骸 `"top_p"`。`__STATIC_END__` marker は**維持**（Part B 後は動的部が常に空になるが、marker の有無が cache_utils に parts 形式＋cache_control で送る合図として機能するため）。

### Part D: cached_tokens 観測

- `openai_compat.py` usage 構築時に `prompt_tokens_details` から cached_tokens を二段 None 防御で取り出し `usage["cached_tokens"]` を追加。
- done SSE（events.py）→ turn-events.js → ダッシュボード usage 表示に passthrough（usage は自由形式 dict、追加キーは既存経路を通る）。ゲートウェイが返さなければ表示省略（縮退許容）。

## 対象ファイル

Python:
- `nous/application/chat/pipeline/compress.py`（Stage 0 削除・Stage 3' 永続基線）
- `nous/application/chat/pipeline/trimmer.py`（固定窓・ハイライト削除、境界探索ヘルパー温存、refs 配線）
- `nous/application/chat/pipeline/summarizer.py`（差分要約・件数上限・refs・フォールバック）
- `nous/application/chat/pipeline/prompt.py`（静的/揮発分離）
- `nous/application/chat/pipeline/inference.py`（top_p 送信削除、[NOUS CONTEXT] 統合注入）
- `nous/application/chat/service.py`（第2切り詰め経路削除、CompressStep へ window 渡し）
- `nous/application/chat/tree_session.py`（`evict_path_head` 公開、history_summary payload）
- `nous/domain/config/compression_config.py`（context_keep_recent_turns 削除）
- `nous/domain/config/provider_config.py`（top_p/dynamic_temperature/emotion_temperature_scale 削除）
- `nous/domain/config/chat_config.py`（_distribute_flat_fields で temperature/max_tokens pop）
- `nous/application/chat/introspection.py`（継承値の確認・必要なら調整）
- `nous/infrastructure/llm/cache_utils.py`（静のみでも parts 形式）
- `nous/infrastructure/llm/openai_compat.py`（cached_tokens）
- `nous/api/http/chat_management.py`（allowlist）

Frontend:
- `nous/api/http/static/chat/settings/`（apply.js / apply-groups.js / reset.js / save.js + sidebar 該当 section）
- `tests/frontend/` 上記 4 テストファイル
- ダッシュボード usage 表示箇所

Docs: `docs/llm_usage_guide.md:446`（top_p 記述削除）。他 docs は grep で top_p/keep_recent/温度の言及を確認し、現行仕様書のみ更新（archive は触らない）。

## テスト計画

- 単体: compress（Stage 0 消失・Stage 3' evict 発火・差分要約・フォールバック・終了条件3種）/ trimmer（境界探索・refs）/ summarizer（件数上限・refs・失敗時 None）/ prompt（静的=期待ブロック、揮発=期待ブロック、分離がバイト安定）/ inference（[NOUS CONTEXT] 統合・top_p 消失）/ chat_config（pop 動作 flat/nested 両形態・保存 JSON 旧キー無視）/ cache_utils（parts 形式）/ openai_compat（cached_tokens 二段防御）
- 保留条件: 既存テストの Stage 0/ハイライト/温度周り前提の更新（test_compress_step / test_trimmer / test_compress_artifact_refs / test_llm_reasoning / test_prompt_* 該当分）
- frontend: 上記 4 ファイル + settings UI の node テスト
- 実機ゲート（ブラウザ）: (1) 実チャットで応答が返る・キャラ一貫性維持 (2) done イベント usage に cached_tokens が出る (3) 長文連投で予算超過を起こし evict+要約注入を devtool ログで確認 (4) 設定 UI から該当項目が消えている・保存が壊れない
- 測定: 修正後、実セッションで cached_tokens が入力トークンの大半を占めることを確認（静的+会話接頭辞が乗る。揮発末尾と最新1メッセージは非キャッシュで正常）。provider 側 64 トークン粒度の境界ロスは誤差として織り込み済み。

## リスク

- プロンプト意味論変化（文脈を会話の後に読む）による応答品質変動 → 実機ブラウザ確認で担保。pi 側で同一構造が実績あり。
- Stage 3' evict は永続的（rollback 不可）。誤切除の危険は切込点仕様（user 境界・tool ペア不破壊）で抑制。evict 切片は要約経由で参照可能。
- キャッシュ境界と切込点が完全一致しない数ブロック分の再送（provider 64tok 粒度）→ 許容。
- 長期運用で history_summary が上限に達した場合の劣化 → 4000 字上限 + 古い方から削る仕様で有界。
