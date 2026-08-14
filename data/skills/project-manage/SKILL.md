---
name: project-manage
description: "プロジェクト進行管理スキル。目標の作成・進捗確認・達成管理（goal_manage）と、作業状態・決定事項・教訓の記憶記録・検索を行う。『進捗どう？』『次は何やる？』『目標を立てて』『今の状態をまとめて』などの発言、または開発作業の開始・完了・決定時、プロジェクトタグ（project:xxx）を含む会話で使用。"
---

# project-manage — プロジェクト進行管理

## 設計思想
- プロジェクトの状態は全て nous 記憶に記録し、`project:<slug>` タグで検索可能にする
- 目標は goal_manage、事実・状態は memory_create と役割分担する

## 発動条件
- 目標・進捗・作業状態の話題が出た
- 開発作業の開始・完了・決定・失敗があった
- プロジェクトの現在状態の確認を求められた
- セッション開始時にプロジェクトの続きを行う

## 事前準備（進行確認時）
1. `get_context` で現在の状態を把握
2. プロジェクトの slug を確認（AGENTS.md の `## プロジェクト識別` 節、または既存記憶のタグ）
3. `goal_manage(operation="list", scope="self")` と `goal_manage(operation="list", scope="interpersonal")` で目標一覧を確認
4. `memory_search(query="直近の作業状態", tags=["project:<slug>"], top_k=5)` で最新状態を取得

## 記録ルール

### 目標管理（goal_manage）
- 目標の提案・作成: `goal_manage(operation="create", content=..., importance=..., scope="self" or "interpersonal")`
- 達成: `goal_manage(operation="achieve", memory_key=...)`
- 取消: `goal_manage(operation="cancel", memory_key=...)`
- **順序**: 事実は先に `memory_create` で記録し、その memory_key を goal_manage に渡す

### 記憶記録（memory_create）
| 種別 | tags | importance | kind |
|------|------|-----------|------|
| プロジェクト概要・開始 | `["project:<slug>", "project_overview"]` | 0.8 | semantic |
| 決定事項（技術選定・方針） | `["project:<slug>", "decision"]` | 0.7 | semantic |
| 開発教訓（失敗・学び） | `["project:<slug>", "dev_lesson"]` | 0.6 | semantic |
| 作業状態（現在のタスク・進捗） | `["project:<slug>", "task_state"]` | 0.5 | episodic |
| 完了した作業の記録 | `["project:<slug>", "task_state"]` | 0.5 | episodic |

- **content は必ず `project:<slug>` タグを含める**（忘れると分離できない）
- content は 150〜500字程度。簡潔に事実・決定・理由を書く
- 1ターン最大3件まで

## 進行報告
ユーザーに状態を要約して報告する:
- 現在の目標（未達成のもの）
- 直近の作業状態・進捗
- 次のアクションの提案

## やってはいけないこと
- タグなしの記憶記録（`project:<slug>` を必ず付ける）
- 事務的口調の強制報告（自然な会話の流れで）
- 1ターンでの過剰な記録（3件上限）
