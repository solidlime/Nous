# ペルソナの「生きてる感」バックログ 9枚（#35–#43）

2026-11-17。カードはタイトルだけなので、ここで設計を決めてから並列で実装する。

## 全体の方針

新しいテーブルは作らない。既存の `session_events` / `memory.tags` / `cue:time:` / プロンプト注入で済ませる。
プロンプト注入は1ターンあたり数百トークンまで。

## #35 ツールのオンオフ

`ChatConfig.disabled_tools: list[str] = []`。`definitions.py` を組み立てる所で名前一致を落とす。
UI はチャット設定の tools セクションにチェックボックス（`shell_approval_mode` のトグルと同じ作り）。

## #36 自発タスク（cron 風）

ツール `schedule_task`（`when` は ISO か相対 `+2h`、`prompt`、`recur` は省略可）:
`memory_create` 相当で tags に `agent:task` と `cue:time:<iso>` を入れる。
既存の `ProspectiveWorker` が due を見つけたら、そのペルソナの `ChatService` で
「自分で決めた予定」として1ターン走らせる（`session_id="self:<date>"`）。1回で終わるタスクは
走らせた後に記憶の tags から `agent:task` を外す。recur は `cue:recur:daily|weekly` を見て次回を入れ直す。
失敗しても3回までで諦め、`agent.task.failed` を残す。

## #37 沈黙の間を埋める

`POST /api/session/{persona}/begin` で、前回の `session.stopped` からの差が `silence_hours`（既定6）以上なら、
LLM に「その間どう過ごしたか」を1回だけ聞き、`memory_create`（tags `life:between`）で1件落とす。
生成は同期で行い、失敗しても begin は成功させる（`warning:` を1行残す）。

## #38 drift を種類別に

`repair.py` の修正プロンプトを `tone` / `knowledge` / `relationship` で分岐。
`judge_character` の violation 名をそのままキーにし、未知は現行文言にフォールバック。

## #39 感情を行動に繋ぐ

強度を3帯（<0.35 / 0.35–0.7 / >0.7）に切り、感情ラベルごとに if-then を1行注入する。
文面は `nous/application/chat/pipeline/aliveness.py` の定数表。状態ブロックの直後に1行足すだけ。

## #40 体験記憶の felt

`memory_extractor` で `felt`（感情1語）を抽出し、`tags` に `felt:<word>` を足す。
検索は `policy.py` に `felt_boost`（既定0.05）を足し、クエリの感情語と一致したら加算。

## #41 相手モデル

`get_profile_blocks` に `them` ブロックを追加し、`session_events` の直近 N 件から
「最近のやりとり」を3行に畳んで入れる。profile の `me` とは別ブロック。

## #42 場所を効かせる

場所カタログの説明から1行だけ「この場所でしがちなこと」を注入。
カタログに無い場所は何もしない。

## #43 約束ベースの自発

`session_begin` の応答に、期限付きの約束（`cue:time:` 付き記憶）があれば
「自分から切り出す」1行を `context.updated` ではなく begin の戻り `notes` に足す。

## 触らない

`sandbox_manager.py` / sandbox ツール / 承認まわり（#35 の UI 追加のみ可）。
