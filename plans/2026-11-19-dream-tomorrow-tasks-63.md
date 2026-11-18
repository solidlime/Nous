# カード #63 — ドリーミングから「明日やること」をタスクスケジューラへ

## 現状
- ドリーミング（`WikiWorker`、既定 03:00 JST）は前日の日記 `journal-YYYY-MM-DD` を書き、
  トピックページを編纂し、感情・体調を日記から反映する（`journal_apply_state`）。
- タスクスケジューラは既にある: `schedule_task`（`nous/application/chat/tools/schedule.py`）
  が `agent:task` + `cue:time:<ISO>` タグの記憶を作り、`ProspectiveWorker` が 1 時間ごとに
  `due_agent_tasks()` で期限到来分を拾って `run_self_turn()` で self-turn を走らせる。
- ただし日記とスケジューラは繋がっていない。日記の「未解決」「決めたこと」は記録されるだけで、
  翌日の行動に変わらない。

## 方針
日記生成の直後に **1 回だけ LLM を呼び**、日記から「明日やること」を最大
`journal_tomorrow_max`（既定 3）件、時刻付きで起こす。各件を既存スケジューラの
`agent:task` + `cue:time:` として記憶に登録する。実行側は新規実装しない
（`ProspectiveWorker` の毎時照合と self-turn がそのまま効く）。

| ファイル | 変更 |
|---|---|
| `nous/config/settings.py` | `WikiConfig.journal_tomorrow_tasks: bool = True` / `journal_tomorrow_max: int = 3` |
| `nous/application/wiki/journal.py` | `_TOMORROW_PROMPT`、`_schedule_tomorrow()`、`_compile_journal` の `_apply_journal_state` 直後に呼び出し |
| `tests/unit/test_wiki_worker.py` | `TestJournalTomorrow`（登録・重複排除・壊れた JSON・無効化） |
| `docs/architecture.md` | WikiWorker サイクルの段に「(4) 日記から明日の予定を登録」を追記 |

## 判断
- **日記本文に節を足さない**: 日記の見出しは 6 つ固定の契約があり、「記録」に予定を
  混ぜない。日記の状態反映（`_apply_journal_state`）と同じく追加 LLM 呼び出し 1 回で分離する。
- **実行時刻の解決**: LLM には `HH:MM` だけ書かせる。日付は cycle の `now` の日付
  （JST）で、`now` 以前の時刻なら翌日に回す。相対表現を LLM に解決させない
  （`schedule_task` の `parse_when` と同じ方針: 保存前に絶対時刻にする）。
- **重複排除**: 既存 `agent:task` の本文と一致するものは登録しない。日記は同じ日に
  2 回走り得る（失敗リトライ）ため、二重登録を防ぐ。
- **失敗は日記を壊さない**: 日記書き込みは完了済みなので、抽出・登録の失敗は
  `warning:` とログに閉じる（`error:` を付けると cycle 失敗扱いで 30 分後の再試行を誘発する）。
- **既存の毎時 sweep をそのまま使う**: 時刻粒度は最大 1 時間。スケジューラの間隔変更は
  本カードの範囲外（必要になったら別カード）。

## 検証
`uv run pytest tests/unit/test_wiki_worker.py -q` / `ruff check` / `ruff format --check` /
`mypy nous/application/wiki/journal.py`。
