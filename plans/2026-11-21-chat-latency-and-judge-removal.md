# チャット応答の遅延要因の全解消（キャラ判定廃止＋6件の性能修正）

- 日付: 2026-11-21
- 基準コミット: `f6b501eb`
- トリアージ: **本格**（複数ファイル・パイプライン／設定／UI／API 変更）

## 背景

`ChatService.chat()` は完全な直列パイプラインで、1ターンあたり LLM を最大 5 往復叩いていた
（本体 + 初回判定 + 再生成 + 再判定 ×2 + MemoryLLM）。実測 p90 135.4s / max 172.6s。

調査で判明した遅延要因は 7 件:

| # | 要因 | 根拠 |
|---|---|---|
| ① | done の後も `end_turn` まで枠を保持し、次の送信が 409 で黙って待たされる | `service.py` の `chat_turn` の `finally: end_turn` |
| ② | キャラ判定が毎ターン 2〜5 往復（修復ループ含む） | `pipeline/repair.py`, `character_judge.py` |
| ③ | PrepareStep の減衰 4 連が毎回 `get_context` を再フェッチ | `prepare.py`, `api/mcp/_tools_helpers.py:612-740` |
| ④ | `_build_relationship_context` が `created_at` 未索引で全走査 ×2 | `context_loader.py:62-86` |
| ⑤ | MCP プールを毎ターン開閉 | 実測で TTL キャッシュ済み。**変更しない** |
| ⑥ | パイプライン段が直列 | 段の並列化は副作用が大きい。**踏襲（変更しない）** |
| ⑦ | 減衰が発動しないターンでも書き込みパスを通る | ③ と同根で ③ の短絡で解消 |

## 方針

- ②は**完全削除**（判定器・修復・設定・UI・SSE・drift 記憶の全経路）。
- ③は`last_conversation_time` を境に「経過 0 分なら 4 連をまるごとスキップ」で短絡。
- ④は索引追加（`schema.py` に移行）＋ 1 ターン内キャッシュ。
- ①は `end_turn` を done 送出直後へ前倒しし、後処理を background task 化。

## 作業分割（担当ファイルを分ける）

### Batch A — キャラ判定の完全削除
- 削除: `nous/application/chat/character_judge.py`, `nous/application/chat/pipeline/repair.py`
- `nous/application/chat/service.py`: import と `RepairStep` 呼び出し、`CHAT_LLM_RESPONSE` の位置
- `nous/application/chat/events.py`: `ResponseReplacedSSE`
- `nous/application/chat/pipeline/context.py`: `drift` フィールド
- `nous/application/chat/pipeline/post.py`: `_memory_payload` の drift
- `nous/application/chat/memory_prompts.py`: `_build_drift_section`
- `nous/application/chat/memory_extractor.py`: drift 受け渡し
- `nous/application/chat/pipeline/context_loader.py`: character_drift セクション
- `nous/domain/config/chat_config.py`: `character_judge_enabled` / `character_repair_max_attempts`
- `nous/api/http/routers/chat/chat_management.py`: 設定キー
- `nous/api/http/sections/chat/chat_sidebar_core.py`: UI
- `nous/api/http/static/chat/settings/{apply,reset,save}.js`
- `nous/api/http/static/chat/send/turn-events.js`, `chat-mode.js`, `turn.js`
- tests: `test_character_judge.py` / `test_repair_step.py` / `test_done_before_character_judge.py` を削除、
  `test_character_drift.py` / `test_post_process_validation.py` を改修

### Batch B — 性能修正
- `nous/application/chat/pipeline/prepare.py`: 減衰短絡
- `nous/infrastructure/db/schema.py`: `idx_session_events_created_at`
- `nous/application/chat/pipeline/context_loader.py`: 関係性コンテキストのキャッシュ
- `nous/application/chat/service.py`: `end_turn` 前倒し＋後処理 background 化

## 検証

- `.venv/bin/python -m pytest tests/unit -q`（基準 3486 passed）
- `.venv/bin/ruff check .` / `ruff format --check .`
- `.venv/bin/mypy nous`（基準エラー数を悪化させない）
- `docs/chat-flow.md` / `docs/architecture.md` / `docs/http_api_reference.md` の同期
