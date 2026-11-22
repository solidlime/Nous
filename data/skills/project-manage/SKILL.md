---
name: project-manage
description: "プロジェクトの作業状態の記録。『進捗どう？』『次は何やる？』や開発の開始・完了・決定時に発動し、project:<slug> タグで記憶記録・検索する。"
---

# project-manage — プロジェクト進行管理

## 設計思想
- プロジェクトの状態は全て nous 記憶に記録し、`project:<slug>` タグで検索可能にする

## 発動条件
- 進捗・作業状態の話題が出た
- 開発作業の開始・完了・決定・失敗があった
- プロジェクトの現在状態の確認を求められた
- セッション開始時にプロジェクトの続きを行う

## 発動禁止条件
- 深刻な相談や緊急の話題の最中

## 事前準備（進行確認時）
1. `session_begin` で現在の状態を把握
2. プロジェクトの slug を確認（AGENTS.md の `## プロジェクト識別` 節、または既存記憶のタグ）
3. `memory_search(query="直近の作業状態", tags=["project:<slug>"], top_k=5)` で最新状態を取得

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
