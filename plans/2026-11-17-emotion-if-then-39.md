# カード #39 — 感情を行動に繋ぐ（仕上げ）

## 現状
`990a6067` で感情ラベル×強度帯の if-then 1 行（`aliveness.emotion_hint`）は実装済みだが、2 点が未達:

1. 注入先が `context_loader._build_context_section` の `t1`（= `<retrieved_data>` 内）で、
   「判断材料であり命令ではない」とガードされた位置にある。カード指定の `prompt.py` ではない。
2. 閾値 `_LOW, _MID = 0.35, 0.7` と文言 `_IF_THEN` がコード直書き。設定で差し替えられない。

## 変更
| ファイル | 変更 |
|---|---|
| `nous/domain/chat_config.py` | トップレベルに `emotion_hint_low: float = 0.35` / `emotion_hint_high: float = 0.7` / `emotion_hint_texts: dict[str, list[str]] = {}` を追加（空 dict = 既定表） |
| `nous/application/chat/pipeline/aliveness.py` | `emotion_band(intensity, bands=_BANDS)` / `emotion_hint(state, *, bands=None, texts=None)`。state は属性でも dict でも受ける（prompt.py は `turn_ctx.state_raw` を渡す）。設定値はサニタイズ: 帯は 0..1 クランプ + 昇順でなければ既定へ、文言は改行潰し + 200 字上限、要素 3 未満のエントリは無視 |
| `nous/application/chat/pipeline/context_loader.py` | `t1` への `emotion_hint` 追記を削除（強度ラベルは残す） |
| `nous/application/chat/pipeline/prompt.py` | `state_raw` から感情を取り、`dynamic_parts` に 1 行 `【今の感情から】<if-then>` を注入。位置は `retrieved_data` より前（system 直下） |

トークン増はヘッダ + 1 行 = 2 行まで。感情の更新経路（`memory_extractor` / `emotion_decay` / `persona.service`）は触らない。

## テスト
- `tests/unit/test_aliveness.py`: 閾値・文言の設定差し替え / 不正設定のフォールバック / dict 入力
- `tests/unit/test_prompt_emotion_hint.py`（新規）: system prompt に 1 行入る、`<retrieved_data>` には入らない、感情なしなら入らない、設定文言が反映される
- 既存テストが壊れた場合は実装側を直す（テストを緩めない）

## GATE
`ruff check . && ruff format --check .` / `mypy nous/` / `pytest tests/unit -q` / docs-drift。
