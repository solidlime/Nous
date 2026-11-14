# Irodori-TTS 調査 — 2026-07-01

## 調査元
[librarian: 40+ sources]

## 基本情報
- 開発: Aratako (個人, 2026-02-25作成)
- スター: 991
- ライセンス: MIT (コード・モデル重み両方)
- アーキテクチャ: Flow Matching + DiT (VITS系ではない)
- モデル: 500M-v3 / 600M-v3-VoiceDesign (3-branch: text + ref + caption)
- 学習データ: 約50,000時間日本語音声

## API
- OpenAI TTS API 完全互換 (Irodori-TTS-Server, FastAPI)
- SSE ストリーミング対応
- Docker: 公式 compose.yaml (GPU/CPU/ROCm)

## 品質
- timbre 0.9745 (6モデル中最高)
- MOS 4.37 (人間録音とほぼ区別不能)

## 弱点
- 漢字読み精度 (pyopenjtalk前処理で緩和可)
- 20-30秒チャンク制限
- 開発者1名、4ヶ月の若いプロジェクト

## 採用: Phase E (独立, 後日着手推奨)

## 詳細: `.spec/SPEC-v3-sillytavern.md` Phase E
