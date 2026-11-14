# ComfyUI ローカル画像生成 調査 — 2026-07-01

## 調査元
[librarian: 22 sources]

## 選定
- **推奨**: ComfyUI (ghcr.io/clsferguson/comfyui-docker)
- **モデル**: Animagine XL 4.0 (SDXL, 日本語キャラ名対応)
- **クライアント**: comfy-api-simplified (MCPサーバ同梱)

## 非選定
- Diffusers: Python内蔵でシンプルだがOOM/キュー管理自前実装必要
- A1111: deprecated (wiki未保守 2023-09-09以降)
- InvokeAI: メンテナが「APIは外部利用想定せず」と明言

## 必要VRAM: 8GB推奨 (4GBでもSD1.5ベースで動作可)

## 詳細: `.spec/SPEC-v3-sillytavern.md` Phase B
