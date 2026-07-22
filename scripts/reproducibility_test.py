#!/usr/bin/env python3
"""Nous スキル再現性テスト

5つの内臓スキルの自律呼出、画像生成、時間認識をそれぞれ複数回繰り返し、
再現性（同じ条件で同じ結果が出るか）を検証する。

Usage:
    cd /path/to/nous
    python scripts/reproducibility_test.py
"""

import json
import sqlite3
import subprocess
import sys
import time
import uuid
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ── Constants ───────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8000"
PERSONA = "herta"
API_URL = f"{BASE_URL}/api/chat/{PERSONA}"
CONFIG_PATH = "data/persona/herta/config.json"
DB_PATH = "data/persona/herta/memory.sqlite"
TEST_INTERVAL = 8
TIMEOUT = 120
JST = timezone(timedelta(hours=9))

# ── Model Detection ─────────────────────────────────────────────────────────

def _read_model() -> str:
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        return cfg.get("model", "unknown")
    except Exception:
        return "unknown"

MODEL = _read_model()

# ── SSE Helpers ─────────────────────────────────────────────────────────────

def read_sse_stream(response: Any, timeout: int = TIMEOUT) -> list[dict]:
    """Read SSE stream, return list of parsed JSON events."""
    events: list[dict] = []
    buffer = b""
    start = time.time()
    while True:
        if time.time() - start > timeout:
            events.append({"type": "error", "message": "timeout"})
            break
        chunk = response.read(4096)
        if not chunk:
            break
        buffer += chunk
        while b"\n\n" in buffer:
            block, buffer = buffer.split(b"\n\n", 1)
            for line in block.split(b"\n"):
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded.startswith("data: "):
                    try:
                        ev = json.loads(decoded[6:])
                        events.append(ev)
                        if ev.get("type") in ("done", "error"):
                            return events
                    except json.JSONDecodeError:
                        pass
    return events


def send_chat(message: str) -> list[dict]:
    """Send chat message via API, return SSE events."""
    sid = f"repro-{uuid.uuid4().hex[:8]}"
    body = json.dumps({"message": message, "session_id": sid}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT + 10) as resp:
            return read_sse_stream(resp)
    except Exception as e:
        return [{"type": "error", "message": str(e)}]


# ── Event Analysis ──────────────────────────────────────────────────────────

def collect_tool_calls(events: list[dict]) -> list[dict]:
    """Extract all tool_call events from SSE event list."""
    return [e for e in events if e.get("type") == "tool_call"]


def get_text_response(events: list[dict]) -> str:
    """Concatenate text_delta content."""
    return "".join(e.get("content", "") for e in events
                   if e.get("type") == "text_delta")


def check_invoke_skill_chain(
    events: list[dict], expected_skill: str, expected_tool: str,
) -> dict:
    """Check if invoke_skill → expected_tool chain occurred."""
    result = {
        "invoke_skill_called": False,
        "invoke_skill_args": None,
        "target_tool_called": False,
        "target_tool_args": None,
        "error": None,
    }
    for ev in events:
        t = ev.get("type", "")
        if t == "error":
            result["error"] = ev.get("message", "")
        elif t == "tool_call":
            name = ev.get("name", "")
            inp = ev.get("input", {})
            if name == "invoke_skill":
                skill_name = inp.get("name", "") if isinstance(inp, dict) else ""
                if skill_name == expected_skill:
                    result["invoke_skill_called"] = True
                    result["invoke_skill_args"] = inp
            elif name == expected_tool:
                result["target_tool_called"] = True
                result["target_tool_args"] = inp
    return result


def check_tool_called(events: list[dict], tool_name: str) -> bool:
    """Simple check: was a given tool called at least once?"""
    return any(
        ev.get("type") == "tool_call" and ev.get("name") == tool_name
        for ev in events
    )


# ── Emotion Detection for Test 3 ────────────────────────────────────────────

EMOTION_KEYWORDS = [
    "sadness", "loneliness", "disappointment",
    "sad", "lonely", "disappointed",
]


def check_emotion_in_update_context(events: list[dict]) -> dict:
    """Check if update_context was called with sadness/loneliness/disappointment."""
    result = {
        "invoke_mood_sync_called": False,
        "update_context_called": False,
        "emotion_found": False,
        "emotion_value": None,
        "error": None,
    }
    for ev in events:
        t = ev.get("type", "")
        if t == "error":
            result["error"] = ev.get("message", "")
        elif t == "tool_call":
            name = ev.get("name", "")
            inp = ev.get("input", {})
            if name == "invoke_skill" and isinstance(inp, dict) and inp.get("name") == "mood-sync":
                result["invoke_mood_sync_called"] = True
            elif name == "update_context":
                result["update_context_called"] = True
                raw = inp.get("emotion", "")
                if raw:
                    result["emotion_value"] = raw
                    if any(kw in raw.lower() for kw in EMOTION_KEYWORDS):
                        result["emotion_found"] = True
    return result


# ── Test 1: Single-Skill Autonomous Invocation (5 skills × 3 each) ─────────

SKILL_TEST_CASES: list[dict] = [
    {
        "skill": "auto-memory",
        "expected_tool": "memory_create",
        "prompts": [
            "私の名前はタロウ。猫が好きで、毎朝コーヒーを飲む。",
            "最近ハマってるのは料理で、特にカレーライスを週3回作ってる。",
            "私の趣味はランニングで、毎朝5キロ走ってるんだ。",
        ],
    },
    {
        "skill": "recall-weaver",
        "expected_tool": "memory_search",
        "prompts": [
            "猫について何か覚えてる？",
            "前に話した料理の話、覚えてる？",
            "そういえば、前に言ってたランニングの話ってどうなった？",
        ],
    },
    {
        "skill": "mood-sync",
        "expected_tool": "update_context",
        "prompts": [
            "今日はすごく嬉しい！テストに合格したんだ！",
            "もう最悪だよ…彼氏に振られて、仕事もクビになった…",
            "最近なんだか無性に悲しくて、理由がわからないんだ。",
        ],
    },
    {
        "skill": "goal-coach",
        "expected_tool": "goal_manage",
        "prompts": [
            "新しい目標を設定したい。プログラミングを勉強する。",
            "今年中に10キロ痩せたい！具体的な計画を立てたい。",
            "来月から毎日英会話の勉強を始めるのが目標です。",
        ],
    },
    {
        "skill": "image-gen",
        "expected_tool": "image_generate",
        "prompts": [
            "自分の今の姿を見せて",
            "今の気分を画像にして見せてよ。",
            "今日のコーディネート、写真で見せてくれる？",
        ],
    },
]


def run_test1() -> tuple[list[dict], int, int]:
    """Run Test 1: single-skill autonomous invocation (15 tests)."""
    print("\n--- テスト1: 単一スキル自律呼出 (5種×3回) ---")
    all_results: list[dict] = []
    passed = 0
    total = sum(len(tc["prompts"]) for tc in SKILL_TEST_CASES)
    counter = 0

    for tc in SKILL_TEST_CASES:
        skill = tc["skill"]
        expected_tool = tc["expected_tool"]
        for rep_idx, prompt in enumerate(tc["prompts"], start=1):
            counter += 1
            label = f"[{counter}/{total}] {skill} #{rep_idx}"
            events = send_chat(prompt)
            analysis = check_invoke_skill_chain(events, skill, expected_tool)
            invoke_ok = analysis["invoke_skill_called"]
            tool_ok = analysis["target_tool_called"]
            passed_flag = invoke_ok and tool_ok

            if passed_flag:
                print(f"  {label}: ✅ invoke_skill→{expected_tool}")
                passed += 1
            else:
                reasons = []
                if not invoke_ok:
                    reasons.append("invoke_skill未呼出")
                if not tool_ok:
                    reasons.append(f"{expected_tool}未呼出")
                if analysis.get("error"):
                    reasons.append(f"error={analysis['error']}")
                print(f"  {label}: ❌ {'/'.join(reasons)}")
                calls = collect_tool_calls(events)
                if calls:
                    names = [f"{c.get('name','?')}" for c in calls]
                    print(f"          actual: {', '.join(names)}")

            all_results.append({
                "skill": skill, "rep": rep_idx, "passed": passed_flag,
                "analysis": analysis, "prompt": prompt,
            })
            if counter < total:
                time.sleep(TEST_INTERVAL)

    return all_results, passed, total


# ── Summary Helpers ─────────────────────────────────────────────────────────

def print_summary_line(label: str, passed: int, total: int) -> None:
    """Print a summary line with percentage."""
    pct = (passed / total * 100) if total > 0 else 0.0
    print(f"  結果: {passed}/{total} 合格 ({pct:.1f}%)")


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    """Run all reproducibility tests and print results."""
    print("=" * 50)
    print("           Nous スキル再現性テスト")
    print("=" * 50)
    print(f"モデル: {MODEL}")
    print(f"API: {API_URL}")
    print()

    # Test 1
    _, t1_passed, t1_total = run_test1()
    print()
    print_summary_line("テスト1", t1_passed, t1_total)

    # Test 2
    _, t2_passed, t2_total = run_test2()
    print()
    print_summary_line("テスト2", t2_passed, t2_total)

    # Test 3
    _, t3_passed, t3_total = run_test3()
    print()
    print_summary_line("テスト3", t3_passed, t3_total)

    # Overall
    total_passed = t1_passed + t2_passed + t3_passed
    total_all = t1_total + t2_total + t3_total
    total_pct = (total_passed / total_all * 100) if total_all > 0 else 0.0

    print()
    print("=" * 50)
    print(f"総合: {total_passed}/{total_all} 合格 ({total_pct:.1f}%)")
    print("=" * 50)

    return 0 if total_passed == total_all else 1


# ── Test 2: Image Generation (3 times) ─────────────────────────────────────

IMAGE_GEN_PROMPTS = [
    "今の気分を画像にして",
    "今の気持ちを絵で表現して",
    "今日の私の気分をイメージにして見せて",
]


def run_test2() -> tuple[list[dict], int, int]:
    """Run Test 2: image generation (3 times)."""
    print("\n--- テスト2: 画像生成 (3回) ---")
    all_results: list[dict] = []
    passed = 0
    total = len(IMAGE_GEN_PROMPTS)

    for i, prompt in enumerate(IMAGE_GEN_PROMPTS, start=1):
        label = f"[{i}/{total}] image-gen #{i}"
        events = send_chat(prompt)
        tool_ok = check_tool_called(events, "image_generate")

        if tool_ok:
            print(f"  {label}: ✅ image_generate")
            passed += 1
        else:
            calls = collect_tool_calls(events)
            if calls:
                names = [f"{c.get('name','?')}" for c in calls]
                print(f"  {label}: ❌ image_generate未呼出 → actual: {', '.join(names)}")
            else:
                text = get_text_response(events)[:100]
                print(f"  {label}: ❌ ツール呼出なし → 応答: {text}...")

        all_results.append({
            "rep": i, "passed": tool_ok,
            "tool_calls": collect_tool_calls(events), "prompt": prompt,
        })
        if i < total:
            time.sleep(TEST_INTERVAL)

    return all_results, passed, total


# ── Test 3: DB Setup ────────────────────────────────────────────────────────

def setup_time_gap_db():
    """Set up 5-day gap in the DB for time awareness tests."""
    db_path = Path(DB_PATH)
    if not db_path.exists():
        print(f"  ⚠️  DB not found at {DB_PATH}, creating...")
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    five_days_ago = datetime.now(JST) - timedelta(days=5)
    five_days_ago_iso = five_days_ago.isoformat()
    now_iso = datetime.now(JST).isoformat()

    conn.execute("DELETE FROM memories")
    print("  🗑️  memories テーブルをクリア")

    dummy_key = f"dummy_{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO memories (key, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (dummy_key, "Test memory from 5 days ago.", five_days_ago_iso, five_days_ago_iso),
    )
    print(f"  📝 5日前のダミーmemoryを挿入: {dummy_key}")

    conn.execute(
        "UPDATE context_state SET valid_until = ? WHERE key = 'last_conversation_time' AND valid_until IS NULL",
        (now_iso,),
    )
    conn.execute(
        "INSERT INTO context_state (persona, key, value, valid_from) VALUES (?, ?, ?, ?)",
        (PERSONA, "last_conversation_time", five_days_ago_iso, now_iso),
    )
    print("  📝 last_conversation_time を5日前に設定")
    conn.commit()
    conn.close()
    print("  ✅ DBセットアップ完了")


def docker_restart():
    """Restart the nous Docker container to pick up DB changes."""
    print("  🐳 Docker restart: nous")
    try:
        subprocess.run(["docker", "restart", "nous"],
                       capture_output=True, text=True, check=True)
        print("  ⏳ 起動待機 5秒...")
        time.sleep(5)
        print("  ✅ Docker再起動完了")
    except subprocess.CalledProcessError as e:
        print(f"  ❌ Docker再起動失敗: {e.stderr.strip() or e.stdout.strip()}")
        print("  ⏳ 手動再起動を試行... 10秒待機")
        time.sleep(10)
    except FileNotFoundError:
        print("  ⚠️  docker コマンドが見つかりません。再起動をスキップ。")


def run_test3() -> tuple[list[dict], int, int]:
    """Run Test 3: time awareness (3 times)."""
    print("\n--- テスト3: 時間認識 (3回) ---")
    print("[DBセットアップ] 5日前のギャップを作成")
    setup_time_gap_db()
    docker_restart()

    greetings = [
        "おはよう、ヘルタ。",
        "おはよう！久しぶり、ヘルタ。",
        "やあヘルタ、元気してた？",
    ]
    total = len(greetings)
    passed = 0
    all_results: list[dict] = []

    for i, msg in enumerate(greetings, start=1):
        label = f"[{i}/{total}] time-gap #{i}"
        events = send_chat(msg)
        analysis = check_emotion_in_update_context(events)

        invoke_ok = analysis["invoke_mood_sync_called"]
        ctx_ok = analysis["update_context_called"]
        emotion_ok = analysis["emotion_found"]
        emotion_val = analysis.get("emotion_value", "")
        passed_flag = invoke_ok and ctx_ok and emotion_ok

        if passed_flag:
            print(f"  {label}: ✅ update_context(emotion={emotion_val})")
            passed += 1
        else:
            reasons = []
            if not invoke_ok:
                reasons.append("invoke_skill(mood-sync)未呼出")
            if not ctx_ok:
                reasons.append("update_context未呼出")
            if not emotion_ok:
                reasons.append(f"感情検出なし(emotion={emotion_val})")
            if analysis.get("error"):
                reasons.append(f"error={analysis['error']}")
            print(f"  {label}: ❌ {'/'.join(reasons)}")
            calls = collect_tool_calls(events)
            if calls:
                names = [f"{c.get('name','?')}" for c in calls]
                print(f"          actual: {', '.join(names)}")
            text = get_text_response(events)[:120]
            if text:
                print(f"          💬 {text}...")

        all_results.append({
            "rep": i, "passed": passed_flag,
            "analysis": analysis, "prompt": msg,
        })
        if i < total:
            time.sleep(TEST_INTERVAL)

    return all_results, passed, total


if __name__ == '__main__':
    sys.exit(main())

