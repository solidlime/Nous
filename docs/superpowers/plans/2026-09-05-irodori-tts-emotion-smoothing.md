# Irodori-TTS Style Anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ON/OFF どちらのパスでも発話内・発話間の感情断絶を止め、内面の違和感など微妙な感情も声に乗せる。

**Architecture:** 変更は `nous/api/http/routers/tts.py` に閉じる。決定的アンカー関数を追加し、OFF はそのまま送信、ON は LLM への固定条件として渡し本文の影響を格下げする。強度バケット＋前回キャッシュで微変動を吸収する。

**Tech Stack:** Python, FastAPI route (Starlette JSONResponse), pytest

## Global Constraints

- `irodori.py` (送信層) は無変更。
- 設定項目の追加なし。`irodori_caption_llm_enabled` の意味はそのまま。
- OFF/ON いずれも caption は自然文1文＋固定接尾辞「全体を通して一貫した声質」で締める。
- LLM 失敗時は OFF アンカーにフォールバックし、無音・500 にしない (合成自体の失敗は従来通り 500)。
- 音声キャッシュキー `_tts_cache_key` の仕様は変えない。

---

### Task 1: `build_style_anchor` 純関数＋単体テスト

**Files:**
- Modify: `nous/api/http/routers/tts.py:23-40`
- Test: `tests/unit/test_tts_style_anchor.py`

**Interfaces:**
- Consumes: 既存 `EMOTION_TONE_HINTS: dict[str, str]`
- Produces: `build_style_anchor(emotion: str, intensity: float, appearance: str | None = None, relationship: str | None = None) -> str`

- [ ] **Step 1: Write the failing test**

```python
from nous.api.http.routers.tts import build_style_anchor

def test_anchor_contains_consistency_suffix():
    a = build_style_anchor("joy", 0.8)
    assert "全体を通して一貫した" in a
    assert "明るく弾んだ" in a

def test_anchor_low_intensity_softens():
    a = build_style_anchor("anger", 0.2)
    assert "抑えめ" in a or "穏やか" in a

def test_anchor_inner_nuance_preserved():
    # 内面系の未知感情はラベルを潰さず残す (違和感の効き対策)
    a = build_style_anchor("違和感", 0.6)
    assert "違和感" in a
    assert "全体を通して一貫した" in a

def test_anchor_empty_emotion_no_crash():
    a = build_style_anchor("", 0.0)
    assert isinstance(a, str) and "全体を通して一貫した" in a

def test_anchor_includes_baseline_when_given():
    a = build_style_anchor("neutral", 0.5, appearance="大人びた雰囲気", relationship="親しい相手")
    assert "親しい相手" in a or "大人びた" in a
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tts_style_anchor.py -v`
Expected: FAIL with "build_style_anchor not defined" (ImportError)

- [ ] **Step 3: Write minimal implementation**

```python
def build_style_anchor(
    emotion: str,
    intensity: float,
    appearance: str | None = None,
    relationship: str | None = None,
) -> str:
    """決定的スタイルアンカー1文。OFF送信・ON固定条件の共通土台。"""
    emo = (emotion or "").strip()
    try:
        inten = float(intensity or 0.0)
    except (TypeError, ValueError):
        inten = 0.0
    inten = max(0.0, min(1.0, inten))
    if emo and emo in EMOTION_TONE_HINTS:
        tone = EMOTION_TONE_HINTS[emo]
    elif emo:
        # 未知・内面系感情はラベルを潰さない (違和感/戸惑い等を残す)
        tone = f"「{emo}」の内面をにじませた話し方で"
    else:
        tone = "普段どおりの自然な話し方で"
    if emo and inten < 0.3:
        tone = "感情を抑えめに、穏やかな話し方で"
    prefix_parts: list[str] = []
    if relationship:
        prefix_parts.append(f"{relationship}に対して")
    if appearance:
        prefix_parts.append(f"{appearance}雰囲気で")
    prefix = "".join(prefix_parts)
    return f"{prefix}{tone}、全体を通して一貫した声質・感情で話す。"
```

配置: `tts.py` の `build_caption_emotion_directive` の直後に追加。既存関数は残す。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_tts_style_anchor.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/routers/tts.py tests/unit/test_tts_style_anchor.py
git commit -m "feat(tts): add deterministic style anchor builder"
```

### Task 2: OFF パス切替 (メタデータダンプ廃止)＋バケット＋前回キャッシュ土台

**Files:**
- Modify: `nous/api/http/routers/tts.py:120-140`
- Test: `tests/unit/test_tts_style_anchor.py` (追記)

**Interfaces:**
- Consumes: Task 1 の `build_style_anchor`
- Produces: モジュール定数 `_LAST_CAPTION: dict[str, tuple[str, float, str]]`、関数 `_emotion_bucket(intensity: float) -> float`

- [ ] **Step 1: Write the failing test**

```python
from nous.api.http.routers.tts import _emotion_bucket

def test_bucket_rounds_to_01():
    assert _emotion_bucket(0.82) == 0.8
    assert _emotion_bucket(0.86) == 0.9
    assert _emotion_bucket(0.0) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tts_style_anchor.py::test_bucket_rounds_to_01 -v`
Expected: FAIL with "_emotion_bucket not defined"

- [ ] **Step 3: Write minimal implementation**

```python
_LAST_CAPTION: dict[str, tuple[str, float, str]] = {}

def _emotion_bucket(intensity: float) -> float:
    try:
        v = float(intensity or 0.0)
    except (TypeError, ValueError):
        v = 0.0
    return round(v + 1e-9, 1)
```

OFF パス置換 (`caption_parts` ダンプ→アンカー1文):

```python
caption_parts = None  # 旧ダンプは廃止
caption = build_style_anchor(
    emotion,
    float(state.emotion_intensity or 0.0),
    appearance=getattr(state, "appearance", None),
    relationship=getattr(state, "relationship_status", None),
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_tts_style_anchor.py tests/unit/test_tts_emotion_caption.py -v`
Expected: PASS (既存テストが壊れていないこと)

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/routers/tts.py tests/unit/test_tts_style_anchor.py
git commit -m "feat(tts): use style anchor for OFF path with intensity bucket"
```

### Task 3: ON パス修正 (本文格下げ・低温・前回継承・フォールバック)

**Files:**
- Modify: `nous/api/http/routers/tts.py:141-226`
- Test: `tests/unit/test_tts_style_anchor.py` (追記)

**Interfaces:**
- Consumes: Task 1–2 の `build_style_anchor`, `_emotion_bucket`, `_LAST_CAPTION`
- Produces: なし (ルーター内完結)。LLM 呼び出しは `temperature=0.2, max_tokens=128`。

- [ ] **Step 1: Write the failing test**

```python
import inspect
from nous.api.http.routers import tts as tts_mod

def test_on_path_uses_low_temperature():
    src = inspect.getsource(tts_mod)
    assert "temperature=0.2" in src
    assert "max_tokens=128" in src

def test_on_system_forbids_text_driven_switch():
    src = inspect.getsource(tts_mod)
    assert "感情の切替は禁止" in src or "切替は禁止" in src
    assert "【固定条件】" in src
    assert "【参考本文" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tts_style_anchor.py -k "low_temperature or forbids" -v`
Expected: FAIL (temperature=0.2 が無い / 固定条件が無い)

- [ ] **Step 3: Write minimal implementation**

1. `llm_system` を以下に置換 (既存の例・制約ブロックは残し、先頭の役割定義と末尾に追記):

```python
llm_system = """あなたは音声合成（irodori-tts）向けキャプション生成AIです。
【固定条件】の感情・アンカーが主です。本文からの感情推測・感情の切替は禁止します。本文は緩急・間・息遣いの参考にのみ使ってください。
前回 caption の声質を維持し、感情が大きく変わった場合のみ寄せてください。
出力は自然な日本語1文 (80文字以内)。必ず「全体を通して一貫した声質・感情で話す。」で締めてください。
... (既存の 含めるべき要素/例/制約は残す。ただし「読み上げテキスト自体の内容から感情を推測して良い」の1行は削除する) ..."""
```

2. `llm_user` を分離形に置換:

```python
anchor = build_style_anchor(
    str(getattr(state, "emotion", "") or ""),
    float(getattr(state, "emotion_intensity", 0.0) or 0.0),
    appearance=getattr(state, "appearance", None),
    relationship=getattr(state, "relationship_status", None),
)
prev = _LAST_CAPTION.get(persona, ("", 0.0, ""))[2]
llm_user = f"""【固定条件】
{anchor}
感情: {state.emotion} (強度: {int((state.emotion_intensity or 0.0) * 10)}/10)

【前回】
{prev or "（なし）"}

【参考本文(感情決定に使わない)】
{text}"""
```

3. バケット一致で再利用 (LLM 呼出前に挿入):

```python
bucket = _emotion_bucket(float(getattr(state, "emotion_intensity", 0.0) or 0.0))
cached = _LAST_CAPTION.get(persona)
if cached and cached[0] == (state.emotion or "") and cached[1] == bucket and cached[2]:
    caption = cached[2]
else:
    ... (既存 LLM 生成。成功したら _LAST_CAPTION[persona] = (state.emotion or "", bucket, caption)) ...
```

4. `temperature=0.7, max_tokens=256` → `temperature=0.2, max_tokens=128` に変更。失敗・空出力時は `caption = anchor` (OFF アンカー) にフォールバック。

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_tts_style_anchor.py tests/unit/test_tts_emotion_caption.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/routers/tts.py tests/unit/test_tts_style_anchor.py
git commit -m "feat(tts): anchor-constrained LLM caption with low temp and reuse"
```
