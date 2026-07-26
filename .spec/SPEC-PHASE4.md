# SPEC — Phase 4: マルチキャラクター・グループチャット

> 出典: `.spec/PLAN.md` (2026-07-26) Phase 4
> 方針: **計画のみ。Phase 2/3 完了後に実装判断。**
> 最終更新: 2026-07-26

---

## 背景

SillyTavern のグループチャットが最も成熟した実装。本フェーズでは同機能の Nous 向け設計を固め、Phase 2/3 の実装状況を踏まえて着手判断する。

## 現状分析

| 項目 | 状態 | 参考 |
|------|------|------|
| セッションモデル | 単一 persona の chat_sessions テーブル | `schema.py:236-244` |
| セッションイベント | persona/session 単位で記録可能 | `schema.py:178-191`, `session_events` テーブル |
| TreeSessionWindow | ツリー構造・編集・ロールバック対応 | `application/chat/tree_session.py:25` |
| SessionManager | LRU eviction（max_sessions=100） | `application/chat/session_manager.py:37` |
| ChatService | 単一 persona 向けパイプライン | `application/chat/service.py` |
| SSE イベント | persona 単位でブロードキャスト | `application/chat/events.py` |

## 設計概要

### 1. セッションモデル

**新規テーブル**: `group_sessions` + `group_session_members`

```sql
-- グループセッション
CREATE TABLE group_sessions (
    group_id TEXT PRIMARY KEY,        -- UUID
    group_name TEXT NOT NULL,
    turn_order TEXT NOT NULL DEFAULT 'round_robin',  -- round_robin | free_form | narrator_driven
    narrator_persona TEXT,            -- ナレーター駆動時のGM役
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 参加メンバー（persona + 役割）
CREATE TABLE group_session_members (
    group_id TEXT NOT NULL,
    persona TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'participant',  -- participant | narrator | observer
    join_order INTEGER NOT NULL,
    PRIMARY KEY (group_id, persona),
    FOREIGN KEY (group_id) REFERENCES group_sessions(group_id)
);
```

### 2. ターン制御

| モード | 動作 | 発言者 | 実装複雑度 |
|--------|------|--------|-----------|
| `round_robin` | 登録順に1人ずつ発言。全員が1巡したら次のラウンド | 現在の persona のみ | 低 |
| `free_form` | 全キャラが毎ターン発言可能。LLM が「誰が喋るべきか」判定 | 全 persona（or そのサブセット） | 中 |
| `narrator_driven` | GM 役が発言権を割り振り。`narrator_persona` が `next_speaker` を決定 | GM + 指名された persona | 高 |

**ラウンドロビン詳細（Phase 4 MVP として推奨）**:
- ユーザー発言 → ペルソナ1 → ペルソナ2 → … → ペルソナN → 次のユーザーターン
- 各ペルソナのターンで通常のチャットパイプライン（PrepareStep → InferenceStep → PostProcessStep）を実行
- 前のペルソナの発言は次のペルソナのコンテキストに含める（`user` ロールで注入）

### 3. 共有コンテキスト設計

**重要**: 「各キャラの視点から見える情報のみを注入」の実装方法

| 概念 | 実装方針 |
|------|---------|
| **公開発言** | 全員のコンテキストに注入 |
| **秘密** | `privacy_level=private` の memory は当該 persona のコンテキストのみに注入 |
| **個別知識** | persona 特有の `persona_state` / `character_card` に従う（既存の挙動維持） |
| **関係性** | `relationship_status` をコンテキストに反映。A が B に話すときは `A→B` の関係性を注入 |

**実装パターン**:
```
各ペルソナのターン:
  1. 前の発言履歴（公開部分のみ）を収集
  2. 当該ペルソナの memory を検索
  3. 当該ペルソナ→他参加者 の relationship_status を取得
  4. コンテキスト組み立て（既存の PrepareStep 流用）
  5. InferenceStep → PostProcessStep
```

### 4. キャラ間インタラクション

| 機能 | 説明 | 優先度 |
|------|------|--------|
| 指名発言 | `@herta それどう思う？` のような発言先指定 | P0 |
| 関係性反映 | persona 間の `relationship_status` が口調に影響 | P1 |
| 競合発言 | 同じターンに複数キャラが反応する場合の調停 | P2 |
| 会話離脱/参加 | キャラが一時的に会話から抜ける/加わる | P2 |

### 5. UI 設計

| 要素 | 内容 |
|------|------|
| メッセージバブル | 発言者 persona の色分け＋アバター（P3-1 のポートレート用画像流用） |
| 参加者リスト | サイドバーに各キャラのステータス（感情＋現在の状態） |
| ターン表示 | 「現在の発言者: ヘルタ」をステータスバーに表示 |
| グループ管理 | キャラ追加/削除、ターン順序編集、発言モード切替 |

### 6. 課題とリスク

| 課題 | 影響 | 対策 |
|------|------|------|
| トークン消費 | 全キャラの会話履歴を保持するためトークン量が N 倍に | CompressStep の積極的活用。軽量会話要約の挿入 |
| レイテンシ | ラウンドロビンで N キャラ分の LLM 呼び出し | 並列 inference（依存関係のないキャラは同時呼び出し） |
| 会話の一貫性 | キャラ A の発言にキャラ B が矛盾する | `MetadataContext` に「前発言の要約」を注入 |
| 無限ループ | キャラ同士の会話が終わらない | ターン数上限の設定 |

### 7. 実装判断基準

Phase 4 の実装に着手するかは以下の条件で判断:

- [ ] Phase 2（記憶階層化 + 感情減衰設定化）が完了
- [ ] Phase 3（UI + マルチモーダル）の P3-1〜P3-4 のうち 3/4 が完了
- [ ] ユーザーがグループチャットを明示的に要望
- [ ] トークン消費・レイテンシに実用上の問題がないことの事前検証

## 学術的基盤・参考実装
- SillyTavern Group Chat: 成熟したマルチキャラクター実装。ターン制御 + 発言コンテキスト管理
- CAST 論文: 複数エージェント間の社会的知覚
- agent-memory: エージェント間の記憶共有パターン

---

## 実装方針（将来）

| 項目 | 方針 |
|------|------|
| 実装方法 | Phase 2/3 のパイプラインを拡張。新規パイプライン `GroupChatService` でラップ |
| 既存コードへの侵襲度 | 低（新規テーブル + 新規サービス。既存 ChatService は変更なし） |
| フロントエンド | 既存チャット UI に `group-chat-*.js` を追加。DOM 構造は共用 |
| テスト | セッション管理・ターン制御はユニットテスト可能。LLM 連携部分は統合テスト |
