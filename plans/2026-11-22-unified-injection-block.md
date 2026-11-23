# 注入ブロックの一本化（チャット ⇔ pi 拡張）— 改訂 5

## 目的
チャット（`nous/application/chat/pipeline/`）と pi 拡張（`pi/extensions/nous-events.ts`）が
**同じタイミング・同じ内容**を注入する。整形を1箇所（Python）に集約し、TS 側の自前レンダラを消す。

## 現状（実測）
| | チャット | pi 拡張 |
|---|---|---|
| タイミング | PrepareStep で毎ターン1回（`prepare.py:216-252`） | `before_agent_start` で毎ターン1回・`messageType !== "user"` で早期 return（`nous-events.ts:565`） |
| 揮発部の順序 | them → active_skills → time_context → emotion → retrieved_data。digest は `inference.py:292` で先頭に join | `formatRecall()` が独自順序で組み立て |
| 状態整形 | `_build_context_section()`（Tier1–3、`context_loader.py:111`） | `formatState()`（7 フィールド・6 グループ、`nous-events.ts:246`） |
| 記憶整形 | `_search_memories()` → `memory_retriever.py:180-205`（annotate + hint） | `formatRecall()` 内で独自整形 |
| 読み上げ抑制 | 静的 `CHARACTER_ADHERENCE_BLOCK`（`prompt.py:173`） | `formatRecall` 末尾の文 |
| ユーザー情報 | 揮発側 `<current_state>`（`context_loader.py:235`） | system prompt `sections.user_identity`（`nous-events.ts:298-302`） |
| digest / time_context / emotion | あり（`prepare.py:85` / `:216` / `prompt.py:186`） | なし |
| 発動中スキル | あり（persona+session 固有、`prompt.py:312-322`） | なし |
| wiki | なし（`chat/pipeline` 配下に "wiki" は 0 件） | あり（`WIKI_TOP_K=2`、サーバーは `limit=3` 固定） |
| min_score ゲート | `_passes_min_score`（`memory_retriever.py:53-59`） | TS 側で `score < config.recall.minScore` を弾く（`nous-events.ts:306,315`） |

## 設計

### 新規 `nous/application/chat/pipeline/injection.py`（**同期**）
`PromptBuildStep.run` は同期（`prompt.py:238`、`service.py:319` で await なし）。よって
**`build_injection_block` は sync** にする。`_build_digest` / `_build_time_context` /
`_emotion_behavior_line` はいずれも sync なので await は不要。
`_build_context_section`（async だが await を含まない）は現状どおり prepare / API ハンドラが
await して `context_section` 文字列を作り、**組み立てだけ**をこの sync 関数に渡す。
→ `service.py` も既存テストも無変更。

```python
def state_to_raw(state) -> dict            # prepare.py:203-210 の内包表記を移設（両経路で共有）
def format_memory_lines(results, *, injected_keys=None) -> tuple[str, list]
                                           # memory_retriever.py:177-205 を切り出し
def format_wiki_lines(hits, k: int = 2) -> str
def build_injection_block(
    ctx, *, time_context: str, state_raw: dict,
    context_section: str, memories: str,
    them: str = "", active_skills: str = "", wiki: str = "",
    config: ChatConfig | None = None,
) -> str
```

**state オブジェクトを引数に取らない**（指摘 #1）。`turn_ctx.time_context` / `turn_ctx.state_raw` は
既に注入インターフェースとして機能しており（`test_prompt_adherence.py:193` は `time_context` を、
`test_prompt_emotion_hint.py:32` は `state_raw` を設定して表明している）、`turn_ctx.state` を新設すると
両テストが黙って壊れる。API 側は共有の `state_to_raw()` / `_build_time_context()` で導出する。
例外2が入力差（減衰）を受容済みなので、導出一元化の利益は最初からない。

**移設**（指摘 #2・循環 import 回避。**injection は injection を import する側、およびされ得る pipeline 側を import しない**。
例外は `aliveness` のみ — `_emotion_behavior_line` が呼ぶ `emotion_hint` の提供元（`prompt.py:8`）で、
stdlib + `nous.domain.persona.places` + `nous.domain.value_objects` しか参照しない葉のため循環しない）:
- `RETRIEVED_DATA_GUARD`（`prompt.py:152`）→ injection.py。`prompt.py` 側は
  `from .injection import RETRIEVED_DATA_GUARD  # noqa: F401` で再輸出（`test_prompt_adherence.py:17` が import している）
- `_emotion_behavior_line`（`prompt.py:186`）→ injection.py、シグネチャは `(config, state_raw)` に変更
- `_build_digest`（`prepare.py:85`）→ injection.py。`prepare.py` 側は noqa F401 再輸出を残す
  （`test_chat_pipeline.py:1544,1554,1566` が `from ...pipeline.prepare import _build_digest` で import）
- `_format_memory_hint`（`memory_retriever.py:27-46`）→ injection.py。切り出した
  `format_memory_lines` がこれを呼ぶため**必ず同時に移す**（移さないと memory_retriever ⇄ injection の双方向 import）。
  `memory_retriever.py` は `from .injection import _format_memory_hint, format_memory_lines  # noqa: F401` で再輸出
  （`prepare.py:24` が `_format_memory_hint` を memory_retriever から再輸出しているチェーンも維持）
- injection は `context_loader` を import しない（`time_context` は文字列で受け取る）

返す文字列（この順序で固定。**唯一の定義**）:

```text
[NOUS CONTEXT]
{digest}                         ← _build_digest(ctx, config)（persona スコープ）
{them}                           ← 【最近のやりとり】chat のみ（session_events 由来、prompt.py:257-259）
{active_skills}                  ← chat のみ（persona+session 固有）
{time_context}                   ← _build_time_context(state)
{emotion_line}                   ← _emotion_behavior_line(config, state_raw)
<retrieved_data>
{RETRIEVED_DATA_GUARD}
<current_state>
{context_section}
</current_state>
<related_memories>{memories}</related_memories>
<related_wiki>{wiki}</related_wiki>      ← 供給された時だけ（pi のみ）
</retrieved_data>
（読み上げ抑制の1文: 内容はそのまま読み上げず、必要な1-2件だけ自然に織り込むこと）
```

- 空セクションは省略。**全セクション空なら `""` を返す**（ヘッダだけの空メッセージを毎ターン注入しない）。
- `<conversation_history_summary>` は CompressStep が `turn_ctx.volatile_context` の末尾へ後から追記する
  （`compress.py:62-71`）。ブロック側の変更は不要。
- `them` は引数化してレイアウトに含める（**指摘 #1**: 落とすと #41 が静かに回帰し、
  ヘッダが合成メッセージの途中に沈む）。
- `prepare.py:252` の `_build_digest` 呼び出しは削除（digest はブロック内部で作る）。
- `config=None` は **境界で正規化**する（`prepare.py:161-162` と同じ形）。`search.py` 側で
  `except Exception: config = ChatConfig(persona=persona)` に倒し、`build_injection_block` は
  `None` を見ない。→ `_build_digest` / `_emotion_behavior_line` に新しいガードは不要。
  （両者は `getattr` ベースなので None でも例外は出ないが、`memory_digest_count` の既定 5 で
  **digest と感情行がそのまま出る**。ガードを足すより境界正規化が小さく、失敗時の挙動も chat と一致する）

### 3 つの消費者
1. **チャット** `prompt.py:257-259`（them の append）を削り、`:312-345` を `build_injection_block(...)`
   1 回に置換。間に挟まる `skills_raw` 読み込みと `static_parts` への `TOOL_USAGE_GUIDELINES` 追加は
   そのまま残す（物理的に連続置換はできない）。統合呼び出しは現 active_skills 位置（`:315` 側）に置く。
   `:259`〜`:315` の間に `volatile_parts` を読むコードは無いので順序は壊れない。
   `_emit_prompt_inject` は挿入確定点なので prompt.py に残し、**発火条件を
   `if turn_ctx.context_section or turn_ctx.related_memories:` として複製する**（指摘 #6。
   元の `if retrieved_inner:` が消えるため、明示しないと常時発火する実装が生まれる）。
2. **pi 拡張** `/api/search/{persona}` の応答に `injection` を追加（`search.py:347` 付近）。
   `state` の生 digest は後方互換で残す。`wiki` 応答欄も現状維持（WebUI 用、`limit=3`）。
   ChatConfig は search.py が今は一切ロードしないので、ハンドラ内で
   `ChatConfigFileRepository(get_settings().data_root).get(persona)` を try/except し、
   失敗時は `ChatConfig(persona=persona)` に正規化（`memory_min_score` と
   `context_compression_mode` の両方に必要）。
   ※ `get()` は不在/破損時にデフォルトを作って `save()` する書き込み副作用を持つ
   （`chat_config.py:356`）。既存の `events.py:66` に前例があるため許容する。TS 側は `parseStatePayload` / `formatState` /
   `formatIdentity` / `applyIdentity` / `formatRecall` を削除し `injection` をそのまま載せる。
   `pi/extensions/_selfcheck.mjs:69-163` はこれらの関数を直接叩いているので、
   `injection` 経路（サーバー応答の文字列をそのまま通す）に書き換える。
   **TS 側の去就を明示する**（指摘 #2）:
   - **削除**: `formatRecall` / `formatState` / `formatIdentity` / `applyIdentity` / `parseStatePayload`、
     および `:562` の `applyIdentity(event)` 呼び出し
   - **残す**: `parseRecallPayload` / `parseWikiPayload` — `recall.injected` イベントの
     `hits` / `wiki_hits` / `wiki_slugs` / status 行 / `top` スコアの導出元（観測データ、nous ジャーナルに流れる）。
     **`WIKI_TOP_K` / `MAX_RECALL_CONTENT` も残す**（`parseWikiPayload` `:177` と `parseRecallPayload` `:317` が
     `MAX_RECALL_CONTENT` を、`:573` の呼び出しが `WIKI_TOP_K` を使う。削ると `tsc` が落ちる）
   - `parseRecallPayload` の `minScore` 引数は**削除**（サーバー側 `_passes_min_score` に一本化）。
     シグネチャは `parseRecallPayload(payload, topK)` にし、`:572` の呼び出しも書き換える
   - `recall.injected` の `min_score: config.recall.minScore`（`:594`）は**落とす**。
     実適用値は persona ChatConfig の `memory_min_score`（サーバー側）で、拡張からは見えない。
     別値を記録し続けると journal の観測が適用実態と乖離する
   - **`config.recall.minScore` 自体も削除**（型 `:372` / パース `:438-439` / 既定 `:464`）。
     この変更後は一切参照されなくなり、残すと `nous.json` の `recall.min_score` が
     無言で効かないノブになる
   - **ゲーティング**: 現在の `hits.length === 0 && wikiHits.length === 0 && !state` 早期 return（`:580-581`）を
     `if (!injection) { setStatus(`nous recall: none · ${ms}ms`); return; }` に置換（`${ms}ms` は残す）
   - `recall.injected` の `state_injected` は `injection.includes("<current_state>")` で導出
   - `content: formatRecall(...)`（`:607`）→ `content: injection`
3. **固定部**は変更しない（`sections.user_identity` のみ廃止 → 下の例外 6）。

### 明示する例外（統一できない/しないもの）
1. **active_skills**: `get_active(persona, session_id)` の persona+session スコープ。pi に渡しようがない。
2. **state の鮮度**: チャットは decay 適用後（`prepare.py:186-199`）、API は
   `persona_service.get_context()` の減衰未適用。GET で書き込み副作用を起こさないため、
   **第1段階では例外**とし decay 統一は別変更に分離する。
3. **retrieval パラメータ**: チャットは persona の `retrieval_*_weight` + 2 クエリ、REST は
   RankPolicy 固定 + 1 クエリ（MCP `memory_search` との等価性コメント `search.py:277-285`）。
   整形のみ共通化し、検索パラメータの統一は別変更。
4. **decay_note**: ターン内差分（`prepare.py:192`・`:195-199`。`:193-194` は circadian でノートを作らない）。chat 専用。
5. **wiki**: chat には無い。pi は `<related_wiki>` として同一ブロック内に載せる。
   整形は `format_wiki_lines(hits, k=2)`（サーバー側で K を決める）。
6. **identity**: `sections.user_identity` を廃止し、ユーザー情報は `<current_state>` に一本化
   （chat と同じ）。**pi では injection が載るターンのみ提供**され、recall 無効・取得失敗・
   `messageType !== "user"` のターンでは名乗りが消える（chat は毎ターン無条件）。
   これは明示的な挙動差として記録する（`applyIdentity` のキャッシュ再適用は削除）。
7. **min_score**（指摘 #3）: pi 経路は persona ChatConfig の `memory_min_score` を
   `_passes_min_score` で適用する（chat と同じゲート）。TS 側の `minScore` フィルタと
   `recall.injected` の `min_score` フィールドは廃止。
   適用範囲は **injection の記憶行のみ**。応答 `results[]` は無フィルタのまま（WebUI の挙動不変）。
8. **全空 + 圧縮発火**: `build_injection_block` が `""` を返しても CompressStep は
   `<conversation_history_summary>` を追記する（`compress.py:70`）。chat では them が
   session_events 由来でほぼ常に非空のため到達困難。**ヘッダなしの要約になることを受容**する。
9. **読み上げ抑制の1文**: 静的 `CHARACTER_ADHERENCE_BLOCK`（`prompt.py:173`）と二重化するが、
   pi には静的ブロックが無いため**ブロック側に残す**（1行の重複として受容）。

### compress_mode
ChatConfig の `context_compression_mode` からのみ。クエリパラメータでの上書きは作らない。

## 触るファイル
- 新規 `nous/application/chat/pipeline/injection.py`
- `nous/application/chat/pipeline/memory_retriever.py`（`format_memory_lines` / `_format_memory_hint` 切り出し＋再輸出。
  `injected_keys` は **should_mention で弾いた後に add**（現行順序を維持）、事前除外 `:159-160` は残す）
- `nous/application/chat/pipeline/prompt.py`（257-259 / 312-345 を置換、`RETRIEVED_DATA_GUARD`・`_emotion_behavior_line` を再輸出）
- `nous/application/chat/pipeline/inference.py`（288-296 から digest join と `[NOUS CONTEXT]` ヘッダを外す）
- `nous/application/chat/pipeline/prepare.py`（`_build_digest` 移設・`recency_digest` 廃止・state_raw 構築を `state_to_raw()` に置換）
- `nous/application/chat/pipeline/context.py`（`recency_digest` 削除のみ）
- `nous/api/http/routers/memory/search.py`（`injection` を返す・`format_memory_lines` 使用・ChatConfig ロード）
- `pi/extensions/nous-events.ts`（5 関数削除・`injection` 使用）
- `pi/extensions/_selfcheck.mjs`（**状態セクションと recall/wiki セクションの両方** `:40-163` を書き換え。
  `:40-41` で `formatRecall` / `parseWikiPayload` を import し `:90` までと `:163` で直接叩いているため、
  ここを直さないと `node pi/extensions/_selfcheck.mjs` が落ちる）
- `docs/http_api_reference.md`（`:209` 付近の Response に `injection` 追記）
- `tests/unit/test_injection_block.py`（新規）+ `recency_digest` を参照する既存テスト

## 検証
- 単体: 同一入力でチャット経路と API 経路が同一文字列（`test_injection_block.py`）
- 順序・ガード・空入力・全空で `""`・chat 専用分（them/active_skills）の非混入
- ChatConfig 取得失敗を注入して `ChatConfig(persona=...)` に正規化されること（min_score が効くこと）
- `npx tsc --noEmit` + `node pi/extensions/_selfcheck.mjs`
- 実起動で `[NOUS CONTEXT]` が1通だけ・`them` がヘッダ直後に残ること
- レイテンシ実測: `/api/search` 3回の中央値（現行 0.22〜0.47s、中央値 0.26s）、追加 +300ms を合格線
