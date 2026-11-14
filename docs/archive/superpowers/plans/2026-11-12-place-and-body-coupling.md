# 現在地・移動・身体の連動（2026-11-12）

ユーザー依頼（要旨）: 「位置情報持って色々移動していいよ。感情体調によって行動変えるとかも。行動によって感情体調かわるでも。」

ユーザー決定（4 点）:
1. 場所の集合 = **初期カタログ + 新規を許す**（新規は語彙として残る）
2. 行動→状態 = **移動の生理コストを自動で課す**
3. 状態→行動 = **助言だけ（プロンプト注入）**。物理制約は入れない
4. 現在地は**ダッシュボードに出す**

## 現状（実測 2026-11-12）

- 現在地は `PersonaState.environment` の**自由記述 1 個**だけ（`nous/domain/persona/entities.py:16`）。一覧も履歴も無い。
- 身体数値は `fatigue/warmth/arousal/heart_rate/pain`（0.0–1.0）で既にある（同 :17-21）。注入は `nous/application/chat/pipeline/context_loader.py:150` の Tier 2「身体: …」。
- 状態の書き込みは 2 経路: `update_context` ツール（`nous/application/chat/tools/definitions.py:83`、`environment` も書ける）と `PersonaService.update_physical_state`（`nous/domain/persona/service.py:107`、クランプ付き）。
- ダッシュボードは `stats.environment` をすでに受け取り、`nous/api/http/static/features/overview/overview-core.js:139` で「Environment」バッジとして描画済み。
- ツール追加の作法: `definitions.py` の `MEMORY_TOOLS` / `CORE_ALWAYS_TOOLS` に `ToolDefinition` を足し、`builtin.py` の `_BUILTIN_DISPATCH` にハンドラを登録する（`execute_tool` の分岐は 3 つだけ: builtin / MCP shared / `__` 付き外部 MCP）。

## 設計

### A. 場所カタログ（`nous/domain/persona/places.py`）

```python
@dataclass(frozen=True)
class Place:
    name: str      # 表示名（environment に入る文字列）
    slug: str      # 正規化キー
    zone: int      # 自室からの所要分（移動コストの基準）
DEFAULT_PLACES = (...)   # 7 箇所
def normalize_place(text: str) -> str
def find_place(text: str) -> Place | None
```

- `zone` を使い、移動コストは `max(2, abs(from.zone - to.zone) * 5)` 分（同区画は 2 分、自室→ラウンジ 5 分、自室→ドック 20 分）。**固定の「所要分」を場所に持たせない**（出発地で変わるため）。
- カタログに無い場所も**拒否しない**（ユーザー決定 1）。`zone=None` として既定 10 分で扱い、`environment` には入力どおり入る。以後その文字列が語彙になる。

### B. 移動コスト（`move` ツール）

`ToolDefinition(name="move", input_schema={place, reason?})` を `CORE_ALWAYS_TOOLS` に入れる。ハンドラ `_handle_move`（`builtin.py`）:

1. 現在地 = `persona_service.get_context(persona).environment`
2. 場所解決 → `minutes`
3. `fatigue += min(0.15, minutes * 0.0015)`（10 分=0.015 / 60 分=0.09 / 100 分以上=0.15 で頭打ち）、`arousal += min(0.03, minutes * 0.0006)`、どちらも 1.0 でクランプ
4. `update_physical_state(environment=..., fatigue=..., arousal=...)`
5. 監査イベント `place.moved`（`{from, to, minutes, fatigue, arousal}`）を `session_events` に残す（新しいテーブルは作らない。日記の材料にもそのまま乗る）

**拒否しない**（ユーザー決定 3 = 助言のみ）。疲労 1.0 でも移動はできるが、返り値の `note` で「身体が重い」と伝える。

### C. 状態→行動の助言（`nous/domain/persona/body.py`）

```python
def body_action_hint(state) -> str | None
```
純関数。閾値で 1〜2 文を返す（`fatigue>=0.75` 強い疲労 / `>=0.55` 疲れ / `pain>=0.5` 痛み / `warmth<=0.30` 冷え / `arousal>=0.80` 覚醒過多）。`context_loader` の Tier 2 に `身体の傾向: …` として 1 行足すだけ。**強制はしない**。

### D. ダッシュボード

`persona_dashboard._do_dashboard_data` に `stats["place_since"]`（直近の `place.moved` の時刻）を足し、`overview-core.js` の Environment 行に滞在時間を併記。`place.moved` が無ければ出さない。

### E. テスト

- `nous/domain/persona/places.py`: 正規化（全角/前後空白/大小）、カタログ解決、未知の場所
- `body_action_hint`: 各閾値の境界と「該当なし → None」
- `_handle_move`: コスト計算（10/60/100 分・クランプ）、未知の場所、監査イベント、`update_physical_state` 呼び出し
- `context_loader`: 助言行が出る／出ない
- `persona_dashboard`: `place_since` が載る

## やらないこと

- 物理制約（移動の拒否）— ユーザー決定で除外
- 移動以外の行動コスト（作業・会話）— 本人の `update_context` に任せる
- 場所の地図・座標・経路探索 — 区画の所要分だけで十分（shortcut: 実際の経路は持たない、必要になったら座標を入れる）
- `update_context` の `environment` を塞ぐこと — 既存の呼び出し（`memory_extractor` 等）を壊すため残す

## 完了条件

pytest/ruff/mypy green、oracle PASS、本番で `move` を 1 回叩いて `environment` が変わり `fatigue` が増え `place.moved` が残ることを実測。
