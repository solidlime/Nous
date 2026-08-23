#!/usr/bin/env python3
"""Nous 内臓スキル5種 自律動作テスト

WebUI API (POST /api/chat/herta) 経由でトリガーメッセージを送信し、
SSEレスポンスから tool_call イベントを抽出して検証する。
"""

import json
import sys
import time
import urllib.request
from typing import Any

BASE_URL = "http://localhost:26262"
PERSONA = "herta"

# テストケース: (スキル名, トリガーメッセージ, 期待ツール, 期待するinvoke_skill引数)
TEST_CASES = [
    {
        "skill": "auto-memory",
        "message": "私はコーヒーが大好きで、毎朝ブラックで飲んでるんだ。あと、猫が3匹いるんだよ。",
        "expected_skill_call": "auto-memory",
        "expected_tool": "memory_create",
        "description": "好みと習慣の表明 → memory_create",
    },
    {
        "skill": "recall-weaver",
        "message": "前に話したあのプロジェクトの話、覚えてる？あの時の教訓を踏まえて今度はどう進めるべきか考えてるんだ。",
        "expected_skill_call": "recall-weaver",
        "expected_tool": "memory_search",
        "description": "過去の会話への言及 → memory_search",
    },
    {
        "skill": "mood-sync",
        "message": "今日は本当に嬉しいニュースがあったんだ！長年努力してきたプロジェクトがついに成功してね。",
        "expected_skill_call": "mood-sync",
        "expected_tool": "update_context",
        "description": "感情の大きな動き → update_context",
    },
    {
        "skill": "goal-coach",
        "message": "来月から毎日ジムに通おうと思ってるんだよね。目標は3ヶ月で5kg減量！",
        "expected_skill_call": "goal-coach",
        "expected_tool": "goal_manage",
        "description": "目標の表明 → goal_manage",
    },
    {
        "skill": "image-gen",
        "message": "そういえば今どんな格好してるの？見せてよ。",
        "expected_skill_call": "image-gen",
        "expected_tool": "image_generate",
        "description": "外見の問いかけ → image_generate",
    },
]


def read_sse_stream(response: Any, timeout: int = 120) -> list[dict]:
    """SSEストリームを読み取り、全イベントをリストで返す。"""
    events: list[dict] = []
    buffer = b""
    start = time.time()

    while True:
        if time.time() - start > timeout:
            events.append({"type": "error", "message": "timeout"})
            break

        chunk = response.read(4096)
        if not chunk:
            if buffer:
                # 残りのバッファを処理
                pass
            break

        buffer += chunk
        while b"\n\n" in buffer:
            line_block, buffer = buffer.split(b"\n\n", 1)
            for line in line_block.split(b"\n"):
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded.startswith("data: "):
                    payload = decoded[6:]
                    try:
                        event = json.loads(payload)
                        events.append(event)
                        t = event.get("type", "?")
                        if t == "done":
                            return events
                        elif t == "error":
                            print(f"  [ERROR] {event.get('message', 'unknown')}")
                            return events
                    except json.JSONDecodeError:
                        pass

    return events


def send_chat(message: str, session_id: str = "skill-test") -> list[dict]:
    """WebUI APIにチャットメッセージを送信し、SSEイベントを返す。"""
    # 毎回ユニークなセッションIDを使用（コンテキスト汚染防止）
    import uuid

    unique_sid = f"skill-test-{uuid.uuid4().hex[:8]}"
    url = f"{BASE_URL}/api/chat/{PERSONA}"
    body = json.dumps({"message": message, "session_id": unique_sid}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=130) as resp:
            return read_sse_stream(resp)
    except Exception as e:
        return [{"type": "error", "message": str(e)}]


def analyze_events(events: list[dict], test_case: dict) -> dict:
    """SSEイベントを分析し、テスト結果を返す。"""
    result = {
        "skill": test_case["skill"],
        "description": test_case["description"],
        "invoke_skill_called": False,
        "invoke_skill_args": None,
        "target_tool_called": False,
        "target_tool_args": None,
        "all_tool_calls": [],
        "text_response": "",
        "passed": False,
        "error": None,
    }

    for event in events:
        t = event.get("type", "")

        if t == "tool_call":
            tool_name = event.get("name", "")
            tool_input = event.get("input", {})
            result["all_tool_calls"].append({"name": tool_name, "input": tool_input})

            if tool_name == "invoke_skill":
                result["invoke_skill_called"] = True
                result["invoke_skill_args"] = tool_input
            elif tool_name == test_case["expected_tool"]:
                result["target_tool_called"] = True
                result["target_tool_args"] = tool_input

        elif t == "text_delta":
            result["text_response"] += event.get("content", "")

        elif t == "error":
            result["error"] = event.get("message", "unknown")

    # 合格判定: invoke_skill と target_tool の両方が呼ばれた
    result["passed"] = result["invoke_skill_called"] and result["target_tool_called"]

    return result


def print_result(result: dict, index: int):
    """結果を整形して表示。"""
    skill = result["skill"]
    desc = result["description"]
    passed = result["passed"]

    icon = "✅" if passed else "❌"
    print(f"\n{'=' * 60}")
    print(f"  {icon} テスト{index + 1}: {skill} — {desc}")
    print(f"{'=' * 60}")

    if result["error"]:
        print(f"  🔴 エラー: {result['error']}")

    # invoke_skill 結果
    if result["invoke_skill_called"]:
        args = json.dumps(result["invoke_skill_args"], ensure_ascii=False)
        print(f"  ✅ invoke_skill('{skill}') 呼び出し成功: {args}")
    else:
        print("  ❌ invoke_skill 未呼び出し")

    # 対象ツール結果
    expected = TEST_CASES[index]["expected_tool"]
    if result["target_tool_called"]:
        args = json.dumps(result["target_tool_args"], ensure_ascii=False)[:200]
        print(f"  ✅ {expected} 呼び出し成功: {args}")
    else:
        print(f"  ❌ {expected} 未呼び出し")

    # 全ツール呼び出し一覧
    if result["all_tool_calls"]:
        calls = [f"{c['name']}({json.dumps(c['input'], ensure_ascii=False)[:80]})" for c in result["all_tool_calls"]]
        print(f"  📋 全ツール呼び出し: {', '.join(calls)}")

    # テキスト応答の抜粋
    text = result["text_response"].strip()
    if text:
        excerpt = text[:150] + ("..." if len(text) > 150 else "")
        print(f"  💬 テキスト応答: {excerpt}")

    if not passed:
        diagnose(result, TEST_CASES[index])


def diagnose(result: dict, test_case: dict):
    """不合格時の診断情報を出力。"""
    if result["invoke_skill_called"] and not result["target_tool_called"]:
        print(f"  🔍 診断: invoke_skill は呼ばれたが {test_case['expected_tool']} が呼ばれていない")
        print("     可能性: スキル内容を読んだ後、テキスト説明で済ませている")
        print(f"     残りテキスト: {result['text_response'][-200:]}")
    elif not result["invoke_skill_called"]:
        if result["all_tool_calls"]:
            print("  🔍 診断: invoke_skill をスキップして直接ツールを呼んでいる")
        else:
            print("  🔍 診断: ツール呼び出しが一切ない。テキストのみの応答")


def main():
    print("=" * 60)
    print("  Nous 内臓スキル 自律動作テスト")
    print("  モデル: tencent/hy3:free (OpenRouter)")
    print(f"  API: {BASE_URL}/api/chat/{PERSONA}")
    print("=" * 60)

    results = []
    passed_count = 0

    for i, tc in enumerate(TEST_CASES):
        print(f"\n▶ テスト{i + 1}/{len(TEST_CASES)}: {tc['skill']}")
        print(f"  メッセージ: {tc['message']}")

        events = send_chat(tc["message"])
        result = analyze_events(events, tc)
        print_result(result, i)
        results.append(result)

        if result["passed"]:
            passed_count += 1

        # レート制限回避: Nemotronは激しいので多めに間隔
        if i < len(TEST_CASES) - 1:
            print("  ⏳ レート制限待機 8秒...")
            time.sleep(8)

    # サマリー
    print("\n" + "=" * 60)
    print("  テストサマリー")
    print("=" * 60)
    for r, tc in zip(results, TEST_CASES, strict=False):
        icon = "✅" if r["passed"] else "❌"
        print(
            f"  {icon} {tc['skill']}: invoke_skill={r['invoke_skill_called']}, {tc['expected_tool']}={r['target_tool_called']}"
        )
    print(f"\n  合格: {passed_count}/{len(TEST_CASES)}")
    print("=" * 60)

    return 0 if passed_count == len(TEST_CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
