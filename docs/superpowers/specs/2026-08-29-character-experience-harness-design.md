# キャラ体験強化ハーネス 設計（RyzaChat:AI 準拠）

- 日付: 2026-08-29
- 状態: 承認済み（ユーザー確認 2026-08-29）
- 参照調査: RyzaChat:AI 機構リサーチ（出典14件）、nous コードベース調査（本 spec 末尾）

## 1. 背景と目的

RyzaChat:AI（SpiralAI × コーエーテクモ、2026-08-25 配信）は「会話だけでキャラクター体験が進む」AI チャットRPG。その体験を構成する要素のうち、nous に取り込むのは**キャラ体験の強化**に絞る:

- 感情に連動した表情差分の自動切替
- 感情に連動した音声トーン
- キャラクター一貫性（性格・口調の厳守、イエスマン化の抑制）

ゲーム状態（持ち物・スタミナ・クエスト・マップ）とモード切替は**対象外**。ただしアイテム管理は既存実装（memory_prompts.py の `inventory_update` 抽出 + item ツールコール、正典は SQLite）が定石どおり動作済みのため、将来のゲーム状態拡張はこの型に乗せられる。

## 2. 決定事項（ユーザー確認済み）

| 項目 | 決定 |
|------|------|
| スコープ | キャラ体験強化（ゲーム状態なし・モード切替なし） |
| 表情の供給源 | ハイブリッド: 事前生成セット主 + 未登録感情は ComfyUI で生成してライブラリに自動追加（自己拡張） |
| アーキテクチャ | A: SSE駆動・バックエンド解決型（フロントは受動） |
| 音声 | 既存 irodori TTS + 自動再生は維持。emotion → caption への連動を追加 |
| キャラ一貫性 | プロンプト構造強化 + 判定器は**フラグのみ**（自動再生成なし） |

## 3. 柱1: 表情ハーネス

### 3.1 データ

- 保存先: persona 画像ディレクトリに `expr_<emotion>.png` 命名で保存
- 配信: 既存の `/api/chat/{persona}/persona/images/{name}` を再利用（新エンドポイント不要）
- 感情ラベル: `PersonaState.emotion` の既存値域に追従（新分類器は導入しない）

### 3.2 バックエンド

- **表情リゾルバ**（小モジュール新設、例: `nous/application/chat/expression.py`）:
  `resolve(persona, emotion) -> URL | None`。ライブラリ照合のみの純関数。
- **差し込み点**: PostProcessStep。emotion が確定・永続化された直後に発火。
  - ライブラリに画像があれば `ExpressionUpdateSSE` を発行（events.py に追加。InventoryUpdateSSE と同型）
  - なければ ComfyUI 生成ジョブを**非同期**で発火（応答をブロックしない）。生成完了後に `expr_<emotion>.png` として保存し、SSE を発行
  - 生成プロンプト: persona の `image_gen_self_portrait_prompt` をベースに感情描写を追加した定数テンプレート
- **失敗時**: warn ログのみ。表示は現状維持。リトライはしない（次の感情変化で自然に再試行）

### 3.3 事前一括生成

- ダッシュボード（persona_dashboard.py）に「表情セット生成」ボタンとエンドポイントを追加
- 基本感情ラベル分を順次 ComfyUI 生成し、ライブラリに保存

### 3.4 フロント

- `static/core/sse.js` に `ExpressionUpdateSSE` 受信を追加
- チャットUIのアバター画像を差し替え（表示位置は実装時に chat_layout.py で確認。アバターが無ければヘッダーに追加）
- 生成中は現状維持（プレースホルダは出さない）

## 4. 柱2: 音声ハーネス（最小差分）

- `routers/tts.py` の caption LLM プロンプトに現在の emotion を渡す
- 感情 → トーン指示のマッピングは小さな定数表（新モジュールなし、コード数行）
- 既存の `voice_auto_play`・autoplay unlock・チャットUIスライダーは変更しない

## 5. 柱3: キャラ一貫性ハーネス

### 5.1 プロンプト側（テンプレート調整中心・コード最小）

- 制約（口調・禁止事項）を文脈末尾近くにも反復配置（recency 活用）
- キャラらしく反論・拒否する few-shot 例の添付
- anti-sycophancy フレーミング: 「ユーザーに仕えるアシスタントではない」の明示
- 対象: persona プロンプト組み立て箇所（PromptBuildStep / memory_extractor.py の注入部分）

### 5.2 判定器（フラグのみ）

- PostProcessStep で副次 LLM 呼び出し（memory_llm.py / memory_extractor.py と同型パターン）
- persona 制約（口調・性格・禁止事項）と応答を照合し、JSON で違反を取得:
  `{violation: "tone" | "compliance" | "character", detail: string}`
- 違反時: チャットUIに警告バッジ（SSE）＋ログ記録。**応答本文は変更しない、再生成しない**
- 判定器自体の失敗: warn ログを必ず残して継続（静黙 fallback の教訓を反映）

## 6. データフロー（応答1回あたり）

```
ユーザー入力
  → Prepare → PromptBuild（感情注入 + キャラ制約反復） → Compress → Inference
  → PostProcess:
      1. memory 抽出（既存）→ emotion 確定・永続化
      2. 表情リゾルバ → ExpressionUpdateSSE（無ければ非同期生成→後でSSE）
      3. キャラ判定器（副次LLM）→ 違反なら警告バッジSSE + ログ
  → TTS（既存、caption に emotion 連動）
```

## 7. エラー処理

| 箇所 | 挙動 |
|------|------|
| 表情画像不在 | ニュートラル/現状維持、非同期生成を発火 |
| ComfyUI 生成失敗 | warn ログ、リトライなし |
| 判定器 LLM 失敗/パース失敗 | warn ログ、フラグなしで継続 |
| SSE 接続切断 | 既存 sse.js の再接続に従う（新規対応なし） |

## 8. テスト方針

- 表情リゾルバ: 単体テスト（存在/不在/命名規約/URL生成）
- ExpressionUpdateSSE: イベント発行・ペイロードのテスト
- 判定器: JSON パース（正常/不正/空）のテスト、違反フラグの伝播テスト
- プロンプト組み立て: スナップショットテスト（制約反復・few-shot の配置）
- 既存 pytest 流儀に従う。カバレッジはプロジェクト基準（≥60%）を維持

## 9. やらないこと（YAGNI）

- ゲーム状態一式（持ち物・スタミナ・コール・クエスト・マップ・調合・戦闘）
- RPG/雑談モード切替
- 判定器違反時の自動再生成ループ
- Live2D / VRM
- go-emotions 等の新規感情分類器
- 音声の ASMR/ささやきモード

## 10. 参照

### コード（現状の差し込み点）

- `nous/application/chat/service.py` — ChatService.chat()、EmotionDrivenSampler (L148)
- `nous/application/chat/pipeline/post.py` — PostProcessStep（L88-94 に「キャラ矛盾/トーン検証なし」の自己言及あり）
- `nous/application/chat/memory_llm.py` / `memory_extractor.py` / `memory_prompts.py` — 副次 LLM + JSON スキーマの既存パターン
- `nous/application/chat/events.py` — SSE イベント定義（InventoryUpdateSSE 等と同型で追加）
- `nous/application/chat/tools/builtin.py` — `_handle_image_generate` (L217)、self_portrait 保存
- `nous/api/http/routers/persona/persona_dashboard.py` — persona 画像配信 (L176-242)、`self_` 接頭辞規約
- `nous/api/http/routers/tts.py` — irodori caption LLM (L122-153)
- `nous/api/http/static/core/sse.js` / `static/chat/` — SSE 受信・チャットUI
- `nous/domain/persona/entities.py` — PersonaState.emotion / emotion_intensity

### 外部調査の要点

- RyzaChat:AI: 表情差分は会話トリガーで切替（手描き30種）、音声は収録音声ベース合成。問題点として文脈リセット・トークン二重課金が報告されている
- 実装定石: 状態の正典は決定論的 DB に置き、LLM は変更を提案、コードが検証する（Latitude World Engine、Ian Bicking の設計論）
- SillyTavern Expression Images: 感情ラベル → スプライト画像切替の最軽量パターン（本設計の柱1に採用）
- キャラ一貫性: プロンプト側の制約配置・few-shot と、出力側の検証（判定器）の二層が定石
