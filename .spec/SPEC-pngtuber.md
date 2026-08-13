# SPEC — PNGTuber 連携（WebUI 組み込み + デスクトップマスコット）

> 出典: ユーザー要望 (2026-08-13)。調査: exp-1（WebUI/TTS/感情/画像生成 API 構造）
> プラン: `.spec/PLAN.md` の「🎮 PNGTuber 連携」セクション

## 背景

ペルソナの立ち絵が「喋る」— チャットに生命感を与える。2 つの表示面を持つ:

1. **WebUI 組み込み**: チャット画面にキャラクター表示（口パク + 感情連動表情）
2. **デスクトップマスコット**: 透過ウィンドウでデスクトップに常駐するキャラクター（バックエンドは WebUI チャット同等 = Nous サーバーの既存 API をそのまま利用）

### ユーザー決定事項
- Electron は重い → **Tauri** でデスクトップアプリ（Rust 環境構築から）
- **WebUI 組み込みを先行**、デスクトップマスコットは後続
- マスコットのバックエンドは Nous サーバー既存 API（SSE チャット + TTS）を利用
- **素材は ComfyUI 生成から必要**（ワークフロー調査 → なければ新規作成）
- **WebUI のアバター位置: 左サイドパネルの最上部**（記憶活動の上）。幅調整可能にする
- **マスコットの吹き出し: 2 行表示 + 自動ストリーミング**（チャット応答をリアルタイムに 2 行で表示）
- Rust 環境構築は自動実行（2026-08-13 に rustup インストール完了 ✅）

### 調査結果（exp-1 要約）
- **TTS 再生**: フロントが `done` SSE 後に `POST /api/tts/{persona}` を叩き、`audio_base64` を `data:audio/wav;base64,...` として `new Audio()` で再生（`chat-tts.js:231-233`, `chat-send.js:627`）
- **感情**: SSE `context_update` イベントでターン中の感情変化を通知。フロントは既に `state.emotion` + `emotion_intensity` を保持（`voice_emotion_link` で使用中）。DB は SQLite `context_state`、減衰は `emotion_decay.py`
- **画像配信**: `GET /api/chat/{persona}/persona/images/{filename}`（`chat_management.py:288`）。生成画像は `{data_root}/persona/{persona}/images/`
- **チャット UI**: `static/chat/*.js`（N.Chat 名前空間）、HTML は `sections/chat/chat_layout.py`、SSE 処理は `chat-send.js`
- **ペルソナ設定**: `{data_root}/persona/{persona}/config.json`（root 所有、編集は `docker exec nous python3`）

## 設計

```
Nous サーバー (既存)
 ├─ POST /api/chat/{persona}        … SSE チャット（context_update で感情通知）
 ├─ POST /api/tts/{persona}         … TTS 音声（audio_base64）
 └─ GET /api/chat/{persona}/persona/images/{filename} … 素材配信
        ↓
共通「アバターエンジン」JS モジュール（`N.Avatar`）
 ├─ 表情管理: emotion → 表情差分画像の切替
 ├─ 口パク: Audio 再生状態 / WebAudio AnalyserNode 音量 → 口開閉
 └─ 素材規約: {data_root}/persona/{persona}/avatar/ ディレクトリ
        ├─ WebUI: チャット画面サイドのアバターパネル（既存チャットに埋め込み）
        └─ Tauri マスコット: 透過ウィンドウ（同じ JS エンジンを流用）
```

**ポイント**: アバターエンジンは JS モジュールとして作り、WebUI と Tauri（WebView ベース）で同じコードを使う。サーバー側の変更は素材配信経路の追加のみで、チャット/TTS/感情の既存 API はそのまま利用。

### 素材規約

`{data_root}/persona/{persona}/avatar/` に配置:

| ファイル | 役割 | 必須 |
|----------|------|------|
| `base.png` | 立ち絵（口閉じ・neutral 表情） | ✅ |
| `mouth_open.png` | 口開き差分 | ✅ |
| `expr_<emotion>.png` | 表情差分（`expr_joy.png` 等） | 任意 |

- 表情差分が無い emotion は base.png にフォールバック
- 表情切替は `<img>` の src 差し替え + 口パクは口開き/閉じの 2 枚切替（画像 2 枚で実現、canvas 合成はしない）
- 口パクの揺らぎは音量に応じた切替周期（AnalyserNode 使用時）or 固定トグル周期（単純モード）
- 素材の生成方法（ComfyUI i2i で口開き差分を生成する等）は Phase 2 以降の任意タスク

## 要件

| # | 要件 | 内容 |
|---|------|------|
| R1 | アバターエンジン | `static/avatar/avatar-engine.js` を新規作成（`N.Avatar` 名前空間）。素材ロード・表情切替（`setEmotion(emotion, intensity)`）・口パク制御（`startTalking()` / `stopTalking()` / `setMouth(openRatio)`）を提供。DOM 非依存の純ロジックと DOM 描画（img src 差し替え）を分離し、Tauri 側で再利用可能にする |
| R2 | 口パク駆動 | TTS 音声再生（`new Audio()`）の `play` / `ended` イベントに連動。音量連動は WebAudio `AudioContext` + `AnalyserNode`（audio 要素を接続、`voice_auto_play` 再生時に有効）。AnalyserNode が使えない環境は固定トグル周期にフォールバック |
| R3 | 感情連動表情 | SSE `context_update` / チャット完了時の `state.emotion` + `emotion_intensity` を `N.Avatar.setEmotion()` に伝播。`expr_<emotion>.png` が無ければ base にフォールバック。感情の強度（intensity）で口パク速度・表情の濃さ（不透明度 or 切替）を変調できるようにする |
| R4 | WebUI 組み込み | チャット画面（`chat_layout.py`）にアバターパネルを追加。**左サイドパネルの最上部**（記憶活動の上）に配置し、**パネル幅をユーザーが調整可能**にする（ドラッグ or 設定値）。パネルの表示/非表示トグルを設定に持つ。スマホ（狭幅）では非表示 or 折りたたみ |
| R5 | 素材配信 | avatar/ ディレクトリの画像を配信する API 経路を追加（既存 `persona/images/{filename}` ルートの拡張 or 新規）。未配置なら 404 ではなくフォールバック（base.png 未配置時はパネル非表示） |
| R6 | 設定 | `config.json` に `avatar` 設定ブロック（`enabled`, `panel_position`, `mouth_mode: "volume" | "toggle"`）を追加。WebUI 設定画面からの編集は Phase 後半（任意）。デフォルトは有効化しない（既存挙動を壊さない） |
| R7 | デスクトップマスコット（Tauri） | Rust 環境構築（完了済み）→ Tauri v2 プロジェクト作成。透過ウィンドウ + ドラッグ移動 + タスクトレイ常駐。Nous サーバーのチャット API を叩くクライアント（SSE + TTS 再生）を持ち、R1 のエンジンでアバターを表示。**吹き出しは応答をリアルタイムで 2 行以内にストリーミング表示**（`text_delta` を逐次反映、超過分は省略） |
| R8 | テスト | アバターエンジンの表情マッピング・口パク状態遷移のユニットテスト（vitest）。Tauri 側は Rust のビルド + 起動確認。UI はブラウザ実機確認（agent-browser） |
| R9 | 素材生成ワークフロー | ComfyUI で立ち絵一式（base + 口開き + 表情差分）を生成するワークフローを用意する（lib-1 調査: 口はマスク inpaint / 表情は FaceDetailer が定石。詳細は「素材生成ワークフロー設計」セクション） |

### 制約
- 既存チャット機能（SSE 処理・TTS 再生・感情トラッキング）の挙動を変更しない。アバターは付加的なレイヤー
- `voice_auto_play` OFF の場合は口パクしない（音声が出ないので）— ただし手動再生時は連動する
- TTS が無効（`voice_enabled: false`）でもアバター表示と表情連動は機能する
- サーバー側 Python 変更は最小限（配信ルート 1 本 + config パース程度）
- MCP ツール変更なし → `docs/llm_usage_guide.md` 更新不要。nous/ 配下コード変更時は docs/README 更新 or `[skip-docs]` 明示

## 素材生成ワークフロー設計（R9 詳細）

> 根拠: lib-1（PNGTuber 素材生成リサーチ）、exp-2（ワークフロー変換器・ComfyUI 到達性実測）

### 方針
- **口開き差分はマスク inpaint で生成**（全画面 img2img は髪・服・背景まで揺れるため不可）
- 表情差分は Phase 2.5（アバター動作確認後に追加）。まず **base + mouth_open の 2 枚**で口パク成立（Veadotube も 2 枚構成を公式認める）
- noobai 系は Danbooru タグがそのまま効く: `open mouth` / `closed mouth` / `smile` / `expressionless`

### ワークフロー構成（API 形式テンプレート `data/workflows/avatar_mouth_open.json`）

```
LoadImage(base.png) ──→ VAEEncode ──→ SetLatentNoiseMask ──→ KSampler ──→ VAEDecode ──→ SaveImage
LoadImageMask(mouth_mask.png, channel=red) ──────────┘
CLIPTextEncode(positive: NOUS:prompt) ──→  ┘
CLIPTextEncode(negative: NOUS:negative_prompt) ──→  ┘
```

- ノードの存在確認済み（ComfyUI 0.32.0 /object_info 実測）: LoadImage ✅ / LoadImageMask ✅ / VAEEncode ✅ / SetLatentNoiseMask ✅ / KSampler ✅ / VAEDecode ✅
- `LoadMask` ノードは ComfyUI 0.32.0 に存在しない → **LoadImageMask + channel 指定**を使用（変換器で変換可能）
- KSampler: denoise 0.6–0.75（マスク領域のみ再生成）。seed は NOUS:seed で注入
- **制約**: 画像パスは動的差し替え不可（`NOUS:reference_image` は未対応・warning のみ）→ base.png / mouth_mask.png は **ComfyUI の input ディレクトリに固定配置**してワークフロー内で参照
- 実行方法: ワークフローを ComfyUI GUI で読み込み → 実行（workflow_source: "comfyui" の Nous 経由実行は画像パス差し替え問題が残るため、まず手動実行。Nous 経由自動化は Phase 2.5 の任意タスク）
- 出力は全画像 2048×2048・同一位置（切替ジャギ防止。PNGTuber の最重要ルール）

### 口開き生成プロンプト例（noobai タグ）
- positive: `open mouth, looking at viewer, solo, masterpiece, best quality, newest, absurdres, highres`
- negative: `closed mouth, parted lips, worst quality, old, early, low quality, lowres, bad hands`

### 背景除去
- 立ち絵は透過 PNG が理想だが、まずは透過なし（背景あり）で動作確認 → 背景除去は Phase 2.5 の任意タスク（RMBG/BiRefNet ノード or 手動）

## フェーズ分割（実装順）

### Phase 1: Rust 環境構築 ✅ 完了（2026-08-13）
- rustup インストール済み。cargo 確認と Tauri v2 の Linux 依存パッケージ（webkit2gtk-4.1 等）導入は Phase 3 着手時に

### Phase 2: WebUI アバター組み込み（先行メイン）
1. アバターエンジン JS（R1）
2. 素材配信 API（R5）
3. チャット UI 組み込み（R4）+ 設定（R6）
4. TTS 口パク連動（R2）+ 感情連動（R3）
5. テスト + ブラウザ実機確認（R8）

### Phase 2.5: 素材生成（R9）
1. 口開き差分ワークフロー `avatar_mouth_open.json` 作成（API 形式・上記設計）
2. base.png を既存 t2i（anima.json）で生成 → ComfyUI input に配置、マスク作成
3. ワークフロー実行 → mouth_open.png を avatar/ に配置 → アバター動作確認
4. 任意: 表情差分（FaceDetailer 方式）、背景除去、Nous 経由の自動生成（NOUS:image タグ拡張）

### Phase 3: デスクトップマスコット（Tauri）
1. Tauri プロジェクト雛形（透過ウィンドウ + ドラッグ + タスクトレイ）
2. Nous API クライアント（SSE チャット + TTS）
3. アバターエンジン流用 + マスコット UI（2 行吹き出し + 自動ストリーミング）
4. ビルド・動作確認

## 検証要件

| # | 項目 | 方法 |
|---|------|------|
| V1 | ユニットテスト | アバターエンジン: 表情マッピング（未対応 emotion → base フォールバック）、口パク状態遷移（start/stop/周期切替）。vitest で追加 |
| V2 | 回帰 | 既存テストが壊れないこと（変更モジュール依存のテストのみ実行） |
| V3 | lint | ruff（Python 変更分）+ stylelint（CSS 変更分）+ eslint（JS 追加分） |
| V4 | UI 実機確認 | agent-browser で: アバターパネル表示/非表示、音声再生で口パク動作、感情変化で表情切替、リロード後も設定維持。Docker 再起動は不要（ライブマウント想定） |
| V5 | マスコット | Tauri ビルド成功（`cargo build`）、アプリ起動・透過ウィンドウ表示・チャット応答表示・TTS 再生・口パク動作 |

## 実装方針
- **Phase 2 はフロント中心**: アバターエンジン（新規 JS）+ chat_layout.py + 配信ルート。設計子（#057）が UI 配置・見た目を担当し、fixer がエンジン/API を担当（並列可能: JS エンジンと Python 配信ルートは独立）
- **Phase 3 は Tauri 知識が必要**: セットアップ手順は librarian（#042）に最新情報を確認してから着手（Tauri v2 の API は変遷が激しい）
- 素材生成（ComfyUI で口開き差分を作る手順）は今回スコープ外の任意タスク。手動で PNG を配置して動作確認する
- ドキュメント: docs/README.md に機能追記 or `[skip-docs]`

## 未確定事項（ユーザー確認）
1. **素材の用意**: 手動で PNG を置いて動作確認 → OK？ （ComfyUI での自動生成は後続）
2. **アバターの位置**: チャット右サイド（メモリパネルと並び）で OK？ チャット内（メッセージ間）埋め込み希望はないか
3. **マスコットの吹き出し**: チャット全文を吹き出しに表示？ 短い要約（1-2 行）を表示？
4. **Rust 環境構築**: こちらで rustup を自動実行してよいか（ホームディレクトリに書き込むため確認）
