# PLAN — 内臓スキル5種テスト (2026-07-21)

## 目的
OpenRouterの `tencent/hy3:free` モデルを使って、Nousの組み込みスキル5種がWebUIチャット経由で自律的に動作することを確認する。
スキルがLLMの指示ではなく自律的に invoke_skill → 対象ツール を呼び出すことが合格条件。

## 背景
- Nousには5つの組み込みスキルが `data/skills/` 配下に存在: auto-memory, goal-coach, image-gen, mood-sync, recall-weaver
- 各スキルはシステムプロンプトに name + description のみ注入され、LLMが `invoke_skill()` を呼ぶことで完全な指示を取得する二段階構造
- hertaペルソナでテストする

## 偵察で見つかった問題
1. herta/config.json で provider が "anthropic" → "openrouter" に修正必要
2. enabled_skills に存在しない "search", "auto-self-portrait" が含まれ、"image-gen" が欠落 → 修正必要
3. プロンプトエンジニアリングが無料モデル向けに最適化されていない可能性

## やること
1. 設定修正 (provider + enabled_skills)
2. プロンプト最適化 (TOOL_USAGE_GUIDELINES + スキルdescription)
3. WebUI API経由のテスト実行
4. 結果分析 → スキル/プロンプト再調整
