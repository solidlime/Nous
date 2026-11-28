---
name: project-manage
description: "プロジェクトの作業状態を project タグで記憶する。次のとき必ず発動する: 『進捗どう？』『次は何やる？』など状態確認を求められたとき、開発作業の開始・完了・決定・失敗があったとき、タスクが完了したとき（task_state メモに completed を付ける更新）、技術選定・方針の決定を会話で決めた直後（decision の記録）、失敗・学びがあった直後（dev_lesson の記録）、セッション開始時にプロジェクトの続きを行うとき（task_state を復元する）。深刻な相談や緊急の話題の最中は発動しない。"
---

# project-manage — プロジェクト進行管理

## 設計思想
- プロジェクトの状態は全て nous 記憶に記録し、`project:<slug>` タグで検索可能にする

## 事前準備（進行確認時）
1. `session_begin` で現在の状態を把握
2. プロジェクトの slug を確認（AGENTS.md の `## プロジェクト識別` 節、または既存記憶のタグ）
3. `memory_search(query="直近の作業状態", tags=["project:<slug>"], top_k=5)` で最新状態を取得

`session_begin` / `memory_search` / `memory_create` が引けない環境では、復元は会話の流れから推定し、記録は hook 抽出に委ねる（このスキルは何もしない）。

## 記録ルール

### 記憶記録（memory_create）
| 種別 | tags | importance | kind |
|------|------|-----------|------|
| プロジェクト概要・開始 | `["project:<slug>", "project_overview"]` | 0.8 | semantic |
| 決定事項（技術選定・方針） | `["project:<slug>", "decision"]` | 0.7 | semantic |
| 開発教訓（失敗・学び） | `["project:<slug>", "dev_lesson"]` | 0.6 | semantic |
| 作業状態（現在のタスク・進捗） | `["project:<slug>", "task_state"]` | 0.5 | episodic |
| 完了した作業の記録 | task_state メモの tags を completed に更新（新規作成は原則しない） | 0.5 | episodic |

タスク完了時は既存メモを更新（memory_update）で完了フラグを付ける。新規 memory_create での完了記録作成はしない。

### タスク完了時の更新
- 作業・タスクが完了したら、**必ずその場で**該当の task_state メモを更新して完了フラグを付ける:
  `memory_update(memory_key=<該当メモのkey>, tags=["project:<slug>", "task_state", "completed"])`
- memory_update の tags は**全置換**なので、元のタグ（project:<slug>、task_state 等）も含めて指定し直すこと。completed だけ渡すと元タグが消える
- 完了フラグは session-start の復元（task_state 検索）で未完了と完了を区別するためのもの。付け忘れると「実施済みなのに未実施のまま」に見える
- 完了後に追加で記録が必要なら、既存メモの更新で足りる場合は更新のみ、新しい事実なら新規 memory_create を使う

- **content は必ず `project:<slug>` タグを含める**（忘れると分離できない）
- content は 150〜500字程度。簡潔に事実・決定・理由を書く
- 1ターンの記憶記録は最大5件まで。nous の hook 抽出が自動記録する環境では重複を避け、本スキルは明示的な状態更新が必要なときに絞る

## 記録との役割分担
事実の episodic 記録は nous hook 抽出がサーバー側で自動に行う。本スキルは `project:<slug>` タグによる明示的な状態記録・更新が必要なときに使う。

## 進行報告
ユーザーに状態を要約して報告する:
- 直近の作業状態・進捗
- 次のアクションの提案

## やってはいけないこと
- タグなしの記憶記録（`project:<slug>` を必ず付ける）
- 事務的口調の強制報告（「タスク#42の進捗を報告してください」等）
- 会話の流れを無視した突然の状態確認
- 1ターンでの記録の詰め込み（hook 抽出側の重複融合同様に抑制せよ）

## ツールの呼び方（環境差）

このスキルが使うツール名は環境で変わる。裸の名前（`memory_search` など）で呼べない場合は、
同じ機能のツールを名前・説明から探して呼ぶ。どの経路でも「機能」で辿れば届く。

- builtin / 拡張ツールとして直接見えている → そのまま呼ぶ
- `mcp__<server>__<tool>` 形式で見えている → その名前で呼ぶ
- MCP Hub 経由（`search_tools` → `get_schema` → `execute_tool`）→ 機能名で検索し、nous サーバーに絞って実行する（例: `search_tools(query="memory search", server="nous")`）
- `ext:mcp-bridge` の `execute_tool` 経由 → `tool_name` に機能名を渡す

見つからないツールを捏造しない。代替が無いときは、その機能を使わずに済む形へ手順を縮める。
