# TODO — PNGTuber 連携（WebUI 組み込み + デスクトップマスコット）

> 出典: `.spec/SPEC-pngtuber.md`（2026-08-13）
> 状態: SPEC 承認待ち。承認後に実装開始。

## Phase 2: WebUI アバター組み込み（先行メイン）

### T1. アバターエンジン JS（R1）— 設計子 #057 が設計・実装
- [ ] T1-1: `nous/api/http/static/avatar/avatar-engine.js` を新規作成（`N.Avatar` 名前空間）
  - 純ロジック（素材マップ・表情選択・口パク状態）と DOM 描画（img src 差し替え）を分離
  - API: `init(element, options)` / `setEmotion(emotion, intensity)` / `startTalking()` / `stopTalking()` / `setMouth(openRatio)` / `destroy()`
  - 表情フォールバック: `expr_<emotion>.png` が無ければ base.png
- [ ] T1-2: ユニットテスト（vitest）: 表情マッピング（未対応 emotion → base）、口パク状態遷移（start/stop/周期切替）
- [ ] T1-3: `static/` の読み込み構成に組み込み（HTML の script タグ or モジュールローダー）

### T2. 素材配信 API（R5）— fixer #011
- [ ] T2-1: `{data_root}/persona/{persona}/avatar/` 配下の画像を配信するルートを追加
  - 既存 `persona/images/{filename}`（`chat_management.py:288`）の拡張 or 新規ルート
- [ ] T2-2: 未配置時のフォールバック（base.png なし → アバター非表示をフロントへ通知）
- [ ] T2-3: テスト（既存ルーターのテストパターン踏襲）

### T3. チャット UI 組み込み（R4）— 設計子 #057
- [ ] T3-1: `sections/chat/chat_layout.py` にアバターパネル追加
  - **左サイドパネルの最上部**（記憶活動の上）
  - **パネル幅をドラッグ or 設定値で調整可能**
- [ ] T3-2: 表示/非表示トグル（設定と連動）
- [ ] T3-3: スマホ（狭幅）では非表示 or 折りたたみ
- [ ] T3-4: CSS 追加（stylelint PASS）

### T4. 設定（R6）— fixer #011
- [ ] T4-1: `persona/config.json` の ChatConfig に `avatar` 設定ブロック追加（`enabled`（既定 false）/ `panel_position` / `mouth_mode: "volume" | "toggle"` / `panel_width`）
- [ ] T4-2: 設定画面 UI（既存パターン踏襲）— 任意（T4-1 のみで Phase 2 完了可）

### T5. TTS 口パク連動（R2）— fixer #011
- [ ] T5-1: `chat-tts.js` の再生処理にフック追加（`audio.play` → `startTalking()`、`ended`/`pause` → `stopTalking()`）
- [ ] T5-2: 音量連動モード: WebAudio `AudioContext` + `AnalyserNode` で audio を解析 → `setMouth(openRatio)`（使えない環境は固定トグル周期にフォールバック）
- [ ] T5-3: `voice_auto_play` OFF でも手動再生時は連動（既存動作は変更しない）

### T6. 感情連動表情（R3）— fixer #011
- [ ] T6-1: SSE `context_update`（emotion 変化）を `N.Avatar.setEmotion()` に伝播
- [ ] T6-2: チャット完了時 `state.emotion` + `emotion_intensity` も反映
- [ ] T6-3: intensity で口パク速度・表情の濃さを変調（低強度 = 弱い反応）

### T7. 検証（R8）
- [ ] T7-1: vitest ユニットテスト PASS
- [ ] T7-2: ruff（Python 変更分）/ stylelint / eslint PASS
- [ ] T7-3: ブラウザ実機確認（agent-browser / Tailscale IP）: パネル表示/非表示・口パク動作・表情切替・リロード維持
- [ ] T7-4: ドキュメント更新（README or docs）or `[skip-docs]` 明示

## Phase 2.5: 素材生成（R9）

### T8. 口開き差分ワークフロー作成
- [ ] T8-1: `data/workflows/avatar_mouth_open.json` 作成（API 形式）: LoadImage + LoadImageMask(channel=red) + VAEEncode + SetLatentNoiseMask + CLIPTextEncode×2 + KSampler(denoise 0.6-0.75) + VAEDecode + SaveImage
- [ ] T8-2: base.png / mouth_mask.png を ComfyUI input に配置する手順を README or docs に記載

### T9. 素材生成実行
- [ ] T9-1: base.png を既存 t2i（anima.json）で生成
- [ ] T9-2: 口マスク作成（MaskEditor or 画像編集）
- [ ] T9-3: ワークフロー実行 → mouth_open.png 生成 → `{data_root}/persona/{persona}/avatar/` に配置
- [ ] T9-4: アバター表示・口パク動作の実機確認

### T10. 任意（後続判断）
- [ ] T10-1: 表情差分（FaceDetailer 方式で joy/sad/angry/surprise）生成
- [ ] T10-2: 背景除去（透過 PNG）
- [ ] T10-3: Nous 経由の自動生成（`comfyui.py:316-322` に `NOUS:image` タグ追加 → LoadImage 差し替え可能に）

## Phase 3: デスクトップマスコット（Tauri）

### T11. Tauri プロジェクト雛形
- [ ] T11-1: Rust ツールチェーン確認（cargo 動作）+ Tauri v2 Linux 依存（webkit2gtk-4.1 等）導入（librarian #042 で最新手順確認）
- [ ] T11-2: `create-tauri-app` でプロジェクト作成（透過ウィンドウ + ドラッグ移動 + タスクトレイ常駐）

### T12. Nous API クライアント
- [ ] T12-1: SSE チャットクライアント（`POST /api/chat/{persona}`、text_delta 購読）
- [ ] T12-2: TTS 取得 + 再生（`POST /api/tts/{persona}` → Audio 再生 → 口パク連動）

### T13. マスコット UI
- [ ] T13-1: アバターエンジン流用（WebView 内で同一 JS）
- [ ] T13-2: 2 行吹き出し + 自動ストリーミング表示（text_delta 逐次反映、超過分は省略）

### T14. ビルド・動作確認
- [ ] T14-1: `cargo build` 成功
- [ ] T14-2: 起動・透過ウィンドウ・チャット応答・TTS・口パクの実機確認
