# PLAN — 2025-07-19

## Memories タブのバグ修正
- Delete が 405 で失敗する。バックエンドは DELETE 定義済みなのに謎。
- Edit ボタン押しても開かない。openEditModal が window に公開されてない疑惑。

## Overview Inventory 編集機能
- 名前と説明を編集できるようにしたい
- バックエンドの PUT /api/items はもうあるらしい。フロントだけ足りない。

## goal_manage ツール確認
- ちゃんと動いてるか確認。動いてなければ直す。

## TTS 音声キャッシュ
- 同じテキスト何度も API 叩いてるの無駄すぎる
- ペルソナごとのディレクトリにキャッシュしたい

## チャットのトークン表示
- 今どきトークン消費量見えないのありえない
- コンテキスト使用率も出したい

## speech コンテキスト廃止 + caption 変更
- speech_style を context_state から消す
- caption フォーマットを変えたい
- LLM に speech_style を覚えさせる仕組みは memory で十分でしょ

## 画像生成: ComfyUI に一本化 + 詳細設定 + LoRA
- openai/stability/gemini/replicate/pollinations 全削除。ローカル生成のみ。
- chat設定に ComfyUI 詳細パネル追加（モデル・LoRA・steps・CFG・sampler・解像度...）
- 疎通状態表示（ヘルスチェック）
- デフォルトモデル: NoobAI-XL Epsilon 1.1
- LoRA 対応: LoraLoader ノード動的追加で初回から対応
- ワークフローをパラメータ駆動に
