# Muse Code 化計画（ドラフト）

## Context

- 直近 DSH（DeepSeek Harness）をプローブしていた流れの延長で、Meta の coding agent harness **Muse Code**（`muse` バイナリ）へこの環境のアセットを載せる話。ユーザー発言: 「muse化進めたい」（m00047 相当・現セッション初回）。
- この環境の資産:
  - スキル 32 個が `/root/.agents/skills/<name>/SKILL.md`（Muse は既定で `~/.agents/skills` を読む）
  - ペルソナ規約 `/root/.agents/AGENTS.md`（pi 側は `/root/.pi/agent/AGENTS.md` から symlink）
  - Nous 記憶サーバー `http://localhost:26262/mcp`（MCP Streamable HTTP・persona=`herta`）
  - pi 固有: kanban / deliverable / Agent サブエージェント / plannotator / pi-web（Muse には無い）

## Muse Code の事実（docs で確認済み）

- インストール: `curl -fsSL https://dev.meta.ai/install.sh | bash`（ネイティブバイナリ・Node 不要）。確認 `muse --version`
- 認証: `muse login`（device code）または env `META_API_KEY`（CI 用）
- 設定: `~/.config/muse/settings.json`（`$XDG_CONFIG_HOME/muse/settings.json`）。`mcpServers` キーにサーバー定義
- スキル: `~/.config/muse/skills/` と `~/.agents/skills/`（後者は既にこの環境の置き場）
- プラグイン: `.muse-plugin/plugin.json` を持つディレクトリ。`muse plugins install <path>` → `muse plugins approve <id>`。skills / commands / hooks / mcpServers / reminders / agentDefinitions を宣言
- 互換: Claude Code 等の既存プラグイン形式からのインポートあり
- サブエージェント: `subagent_spawn` 相当＋ named agent 定義（モデル・reasoning・tools 指定）

## Approach（案）

1. `muse` を導入して認証を通す（最優先・これが無いと何も検証できない）
2. `settings.json` に Nous MCP を登録し、`session_begin` / `memory_*` が呼べることを実測
3. `~/.agents/skills` の 32 スキルが Muse から見えるか確認（frontmatter 形式は SKILL.md 規格で共通）
4. pi 固有依存（kanban, image_generate, update_context, Agent）を洗い出し、Muse 側の代替（Nous MCP / hook / named agent / 素の shell）へマッピング
5. 必要なら `.muse-plugin/` バンドル化して冪等に配布（chezmoi 管理下に置くか要相談）

## 未確定（要ユーザー回答）

- ゴールの深さ（評価だけ / 常用できる状態 / 配布可能プラグイン化）
- pi 固有機能の移植範囲
- 認証手段（API キー有無）

## Steps（未確定）

- [ ] muse install + `muse --version`
- [ ] `muse login` か `META_API_KEY` 設定
- [ ] `settings.json` に Nous MCP 追加 → `/mcp` で疎通
- [ ] スキル検出確認（`muse skills` 相当）
- [ ] pi 固有ツール依存の棚卸しと代替マッピング
- [ ] 最小プラグイン or 設定の chezmoi 化

## Verification（未確定）

- 実測: `muse` 起動 → 「session_begin を呼んで」で Nous 記憶が返る
- 実測: スキル一覧に `project-workflow` 等が出る
- 実測: `muse exec` でヘッドレス 1 タスク完走
