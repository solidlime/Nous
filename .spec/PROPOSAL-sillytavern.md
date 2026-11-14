# PROPOSAL v3 — SillyTavern + ComfyUI + Irodori-TTS 採用計画 (2026-07-01)

> **フェーズ分けと仕様詳細は以下を参照**:
> - 要件定義: `.spec/SPEC-v3-sillytavern.md`
> - タスク分解: `.spec/TODO-v3.md`
> - 人間用メモ: `.spec/PLAN.md`

## エグゼクティブサマリ

Phase 0-3 (レビュー対策) が完了した Nous に対して、3つの生きた次元を追加する:

| 次元 | 技術 | ライセンス | 工数 | リスク |
|------|------|-----------|------|------|
| **Dynamic Temperature** | 自前実装 (emotion_decay 活用) | MIT | 小 | 低 |
| **ペルソナ動的画像** | ComfyUI (外部PC, HTTP API) + Animagine XL 4.0 | GPL-3.0 (backend ok) | 中〜大 | 中 (VRAM, コスト制御) |
| **日本語音声** | Irodori-TTS (外部PC, OpenAI API互換) | MIT | 中 | 中 (若いプロジェクト, GPU必須) |

## 環境構成

```
Nous Server (CPU) ──HTTP──▶ ComfyUI PC (GPU 8GB+, :8188)
        │
        └──────────HTTP──▶ Irodori PC (GPU 8GB+, :8088/v1)
```
**両方とも外部サービス前提**。Nous の Docker Compose には含めず、URL 設定で接続。

## Phase 概要

### Phase A: Dynamic Temperature
感情に応じて LLM の temperature を動的調整。`EmotionDrivenSampler` 純粋関数 → pipeline orchestrator が事前計算。

### Phase B: ペルソナ動的画像生成
ComfyUI でローカル画像生成。Animagine XL 4.0 アニメモデル。**デフォルト完全OFF** (PortraitGenerationConfig でガード)。

### Phase C: WebUI リアルタイム化
SSE で感情/身体状態/ポートレート更新をリアルタイム通知。

### Phase D: SillyTavern 採用 (縮小)
Author's Note 常時注入 + PNG メタデータ Persona Card。Lorebook は Qdrant で十分のため降格。

### Phase E: Irodori-TTS 音声統合
MIT ライセンス、日本語専用、OpenAI 互換 API。絵文字+キャプションで感情制御可能。

## 調査ドキュメント
- `docs/archive/research/sillytavern-features-2026-07-01.md` — SillyTavern 機能調査 (32件)
- `docs/archive/research/comfyui-local-image-gen-2026-07-01.md` — ComfyUI 調査 (22件)
- `docs/archive/research/irodori-tts-2026-07-01.md` — Irodori-TTS 調査 (40+件)
