# SPEC: webuiチャットのコンテキスト注入強化

- date: 2026-08-22
- status: approved (design)
- related: SPEC-nous-unification.md, docs/memory_features.md

## 背景・問題

opencode 側では session-start スキル + get_context により「プロジェクト単位の引継ぎ + その他コンテキスト」が毎ターン注入される。一方 webui チャットはチャットログ依存が強く、同一ストア内の opencode セッション由来の記憶が自動的に表面化しない。手動 `memory_search` の方が効いているように感じるのは、自動 recall が弱いため。

原因（調査済み）:

1. 自動recallが直近1ターンのクエリのみ・top_k=3（`memory_preload_count` デフォルト）
2. trimmer が関連記憶セクションを最優先トリム対象にしている（ログ保護優先の設計思想）
3. get_context の Recent Memories 相当＝クエリ一致不要な「最近のできごと」ダイジェストが存在しない
4. session_summary 取得が順序不定（`get_by_tags` に sort 指定なし）、`task_state` タグは未注入

## 目標

- opencode で会話した内容が、webui チャットに自然に引き継がれる（手動検索不要）
- チャットログの連続性は維持しつつ、圧力下でも記憶系コンテキストが即死しない
- 話題が過去の記憶に関連する場合、モデルが能動的に memory_search する

## 非目標

- RecallGovernor の有効化（max_tool_calls が既存の頻度制限として機能するため触らない）
- webui チャットへの AGENTS.md / コードベース文脈の注入（スコープ外）
- Essential Story セクションの新設（既存 Tier3 構成の範囲で対応）

## 設計

### §1 Recency digest（新規・引き継ぎの本体）

- 直近の記憶を `updated_at` 降順で N 件取得し、「最近のできごと」として毎ターン注入する。**クエリ一致不要**——opencode 側で記録された記憶が自動的に流れ込む経路。
- N = 新 config `memory_digest_count`（デフォルト 5、0 で無効）。
- 各エントリは content 冒頭約200字＋相対時刻（例: `(2h ago)`）。タイムスタンプ表記は設定されたタイムゾーンに従う（inference.py:135 の JST 固定表記問題を本実装内で同時修正）。
- **配置**: system プロンプトではなく、最新 user 発言の直前に合成メッセージとして挿入する。履歴には永続化せず毎ターン再構築する。attention の近接性によりログ支配に対抗する。
- 形式例:

```
[最近のできごと — 他クライアントとの活動を含む]
- (2h ago) chezmoi 同期も完了。dotfiles リポジトリに3コミット…
- (1d ago) T013 リファクタリング完了+実機スモークテスト合格…
```

### §2 既存 recall の強化

- クエリ拡張: 「最新 user 発言 + last_assistant[:200]」→「直近ユーザー発言 最大3件の結合」（合計800字上限、超過時は新しい方から採用）。話題連続性を確保する。
- `memory_preload_count` デフォルト 3 → 5。
- session_summary 取得（context_loader.py:239 付近）に `sort=updated_at` を指定し最新を保証する。
- Tier3【あなたの記憶と洞察】に `task_state` タグ付き記憶を追加注入（session_summary と同様の上位N件方式）。

### §3 Trimmer 優先度の変更

- 現状: 圧縮時、関連記憶セクションが最優先トリム → 「他N件 — memory_searchで検索」に置換。
- 変更後トリム順: 古いログ要約 → 関連記憶/digest → 直近ターン。ログは保護しつつ、中程度の圧力では記憶系が生き残る。

### §4 自律 recall 指示

- base_prompt に一行追記:「会話の話題が過去の記憶と関連しそうなとき・話題が切り替わったときは、memory_search ツールで能動的に検索せよ」。
- 頻度制御は既存 max_tool_calls に委ねる。

## データフロー

```
PrepareStep:
  - _search_memories(拡張クエリ) → 関連記憶（system 内 ---関連記憶---）
  - _build_digest() → 直近N件（§1 用、updated_at 降順）
InferenceStep:
  - messages = [...history..., digest合成メッセージ, 最新user]
PostProcessStep:
  - auto_extract / reflection（変更なし）
```

## エラーハンドリング

- digest 対象 0 件 → 合成メッセージ自体を挿入しない。
- 記憶ストア障害時 → digest/recall は空で継続（チャットを落とさない）。既存 recall と同じ失敗時挙動。

## 設定変更

| key | 変更 | 既定値 |
|-----|------|--------|
| `memory_digest_count` | 新設 | 5（0で無効） |
| `memory_preload_count` | 既定値変更 | 3 → 5 |

- **両キーとも webui 右カラムの設定パネルから編集可能にする**。既存の `memory_preload_count` と同じ UI パターン（`nous/api/http/static/chat/chat-settings.js`:178 set / :392 read）に倣い、数値入力として追加する。
- config 実体は `nous/domain/compression_config.py`（pydantic + field_validator）。`memory_digest_count` には 0 以上のバリデーションを追加する。

## 対象ファイル（想定）

- `nous/application/chat/pipeline/prepare.py` — クエリ拡張、digest 構築
- `nous/application/chat/pipeline/inference.py` — 合成メッセージ挿入、タイムゾーン表記修正
- `nous/application/chat/pipeline/context_loader.py` — session_summary sort 指定、task_state 注入
- `nous/application/chat/pipeline/trimmer.py` — トリム優先度
- `nous/domain/compression_config.py` — `memory_digest_count` 新設、`memory_preload_count` 既定値変更
- `nous/api/http/static/chat/chat-settings.js`（+ 設定パネル HTML）— 右カラムへの設定UI追加
- base_prompt 定義 — §4 の一行

## テスト計画

- 単体: digest 構築（件数・ソート・トリミング・0件スキップ）/ クエリ拡張 / trim 順序 / task_state 注入 / session_summary sort / `memory_digest_count` バリデーション
- 設定UI: 右カラムから両キーを変更 → 保存 → 再読込で反映されること（round-trip）
- 回帰: 既存 chat pipeline テスト一式
- 手動確認: opencode で記録した直近記憶が、webui 新規チャットの初回応答に反映されること（実ブラウザ）
