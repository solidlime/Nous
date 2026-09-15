# 記録: 「過去の記憶が直近扱い」問題の対策（時間文脈の明示）

- 日付: 2026-09-15
- コミット: c7301d5f feat(memory): 時間文脈の明示と recency 既定値で「過去記憶が直近扱い」問題を緩和

## 調査で確定した原因（4箇所）

1. MCP `memory_search` の結果 JSON に時刻フィールドが無く、LLM が記憶の古さを知り得ない（`nous/api/mcp/_tools_memory.py`）
2. `_format_lightweight_response` の Essential Story / Recent Insights / Recent Summaries に時刻表記ゼロ
3. リフレクションが 24h ウィンドウ空のとき `or recent[:10]` で年単位の古い記憶を拾い、時刻なしプロンプトで誤認を新しい記憶に焼き込む（`nous/application/chat/reflection.py`）
4. 道具経路の `recency_weight` 既定 0.0 で RRF recency ボーナス（`nous/domain/search/ranker.py`、`1/(1+age_days)`）が不発

## 実装（全て追加的・後方互換、DB スキーマ無変更）

- memory_search 結果に `created_at`/`updated_at`（ISO）+ `age`（**created_at 基準**。updated_at はエンリッチ更新で若返るため錨不可）
- `MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT = 0.05`（単一定数、tools.py スキーマと参照共有）
- get_context 注入の 3 セクションに相対時刻付与。Behavior Patterns は集約概念のため時刻なし
- リフレクション: 24h フォールバック廃止・空なら skip（info ログで可観測化）、両プロンプトに時刻+混同禁止指示

## 教訓

- **RRF と recency ボーナスのスケール差**: RRF は rank ベースで隣接順位差 ~0.0001 に対し、recency ボーナスは絶対値（30日で 0.032 に減衰）。重み 0.2+importance 0.3 で「0.9適合/30日前 vs 0.5適合/1時間前」が逆転する。0.05 なら解消。**年単位の古さ差ではいかなる正の重みでも逆転しうる**——これは仕様（古さは潰さず age フィールドで LLM に伝える）
- **委譲基盤の不安定性**: subagent（Explore/fixer）は途中停止や遅延が頻発。fixer は実は生きていて後から差分を出した——「死んだ」と断定する前に `git status` で差分を確認すること
- **stash からの復元漏れが 2 回発生**: stash → 長時間コマンド → pop の流れは、pop を必ず即座に別ステップで実行するか stash を使わないこと
- mypy はベースライン自体が不健全（357 errors）。差分比較でのみ Gate 判定可能（今回 −5）

## 残存課題

- `updated_at` が `update()` のたび現在時刻に上書きされる問題（`nous/infrastructure/sqlite/memory_crud_repo.py:181` 付近）は未修正。find_recent（updated_at 降順）が古い記憶を「直近」に浮上させる経路が残る。次タスク候補: find_recent を created_at 降順に変更、またはエンリッチ系更新で updated_at を touch しない
- recency_weight 0.05 の実運用での体感検証
