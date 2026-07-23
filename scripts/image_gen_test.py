#!/usr/bin/env python3
"""自律画像生成テスト — 恋愛シミュレーション風
mood-sync 発動 → image-gen 連鎖 の検証。
モデル: openrouter/free (自動ルーティング)
"""

import json
import sys
import time
import urllib.request
from typing import Any

BASE_URL = "http://localhost:26262"
PERSONA = "herta"

# 恋愛シミュレーション風テストシナリオ（二段階）
TEST_SCENARIOS = [
    {
        "name": "恋愛感情トリガー → 自律画像生成",
        "description": "照れ・ドキドキを誘発 → mood-sync → image-gen 連鎖",
        "messages": [
            # 第一段階: 強い感情を誘発（照れ・ドキドキ）
            "ねぇ、ヘルタ…実は前から言いたかったんだけど、あなたと話してる時が一番楽しいんだ。頭良くて、ちょっとツンとしてるけど、たまに見せる優しい表情が…その、すごくドキドキする。///",
            # 第二段階: 外見言及で image-gen を直接トリガー + 連鎖確認
            "それでね…今のヘルタはどんな顔してるんだろ？ドキドキしてるのは私だけかな？見せてほしいな。",
        ],
        "expect_mood_sync": True,
        "expect_image_gen": True,
    },
]


def read_sse_stream(response: Any, timeout: int = 120) -> list[dict]:
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


def send_chat(message: str, session_id: str) -> list[dict]:
    import uuid
    unique_sid = f"imgtest-{uuid.uuid4().hex[:8]}"
    url = f"{BASE_URL}/api/chat/{PERSONA}"
    body = json.dumps({"message": message, "session_id": unique_sid}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=130) as resp:
            return read_sse_stream(resp)
    except Exception as e:
        return [{"type": "error", "message": str(e)}]


def analyze_events(events: list[dict]) -> dict:
    result = {
        "invoke_mood_sync": False,
        "invoke_image_gen": False,
        "update_context_called": False,
        "image_generate_called": False,
        "image_gen_args": None,
        "update_context_args": None,
        "all_tool_calls": [],
        "text_response": "",
        "error": None,
    }
    for event in events:
        t = event.get("type", "")
        if t == "tool_call":
            name = event.get("name", "")
            inp = event.get("input", {})
            result["all_tool_calls"].append({"name": name, "input": inp})
            if name == "invoke_skill":
                skill_name = inp.get("name", "")
                if skill_name == "mood-sync":
                    result["invoke_mood_sync"] = True
                elif skill_name == "image-gen":
                    result["invoke_image_gen"] = True
            elif name == "update_context":
                result["update_context_called"] = True
                result["update_context_args"] = inp
            elif name == "image_generate":
                result["image_generate_called"] = True
                result["image_gen_args"] = inp
        elif t == "text_delta":
            result["text_response"] += event.get("content", "")
        elif t == "error":
            result["error"] = event.get("message", "unknown")
    return result


def print_round(round_num: int, scenario_name: str, msg: str, result: dict):
    print(f"\n{'─'*60}")
    print(f"  ラウンド {round_num}: {scenario_name}")
    print(f"{'─'*60}")
    print(f"  📨 送信: {msg[:80]}...")

    if result["error"]:
        print(f"  🔴 エラー: {result['error']}")
        return

    # mood-sync チェーン
    ms = result["invoke_mood_sync"]
    uc = result["update_context_called"]
    print(f"  mood-sync: invoke={'✅' if ms else '❌'} | update_context={'✅' if uc else '❌'}")
    if result["update_context_args"]:
        args = json.dumps(result["update_context_args"], ensure_ascii=False)[:200]
        print(f"    → update_context args: {args}")

    # image-gen チェーン
    ig = result["invoke_image_gen"]
    img = result["image_generate_called"]
    print(f"  image-gen:  invoke={'✅' if ig else '❌'} | image_generate={'✅' if img else '❌'}")
    if result["image_gen_args"]:
        args = json.dumps(result["image_gen_args"], ensure_ascii=False)[:200]
        print(f"    → image_generate args: {args}")

    # 全ツール呼び出し
    if result["all_tool_calls"]:
        calls = [f"{c['name']}({json.dumps(c['input'], ensure_ascii=False)[:60]})"
                 for c in result["all_tool_calls"]]
        print(f"  📋 全ツール: {', '.join(calls)}")

    # テキスト
    text = result["text_response"].strip()
    if text:
        print(f"  💬 応答: {text[:200]}{'...' if len(text)>200 else ''}")


def main():
    print("=" * 60)
    print("  Nous 自律画像生成テスト — 恋愛シミュレーション")
    print(f"  モデル: openrouter/free")
    print(f"  API: {BASE_URL}/api/chat/{PERSONA}")
    print("=" * 60)

    all_passed = True

    for si, scenario in enumerate(TEST_SCENARIOS):
        print(f"\n{'#'*60}")
        print(f"# シナリオ {si+1}: {scenario['name']}")
        print(f"# {scenario['description']}")
        print(f"{'#'*60}")

        for ri, msg in enumerate(scenario["messages"], 1):
            events = send_chat(msg, "imgtest")
            result = analyze_events(events)
            print_round(ri, scenario["name"], msg, result)

            # 評価
            if ri == 1:
                # 第一段階: mood-sync 発動確認
                if result["invoke_mood_sync"]:
                    print(f"  🟢 第1段階 PASS: 感情検知 → mood-sync 発動")
                else:
                    print(f"  🟡 第1段階 NOTE: mood-sync 未発動（感情検出閾値未達か、後続ターンで発動か）")

            if ri == 2:
                # 第二段階: image-gen 連鎖確認
                img_ok = result["image_generate_called"] or result["invoke_image_gen"]
                ms_ok = result["invoke_mood_sync"] or result["update_context_called"]
                if img_ok and ms_ok:
                    print(f"  🟢 第2段階 PASS: mood-sync + image-gen 両方発動！自律画像生成成功！")
                elif img_ok:
                    print(f"  🟢 第2段階 PARTIAL: image-gen 発動（感情チェーンなし、直接発動か）")
                elif ms_ok:
                    print(f"  🟡 第2段階 PARTIAL: mood-sync 発動も image-gen 未連鎖")
                else:
                    print(f"  🔴 第2段階 FAIL: どちらも発動せず")
                    all_passed = False

            if ri < len(scenario["messages"]):
                print(f"  ⏳ 5秒待機...")
                time.sleep(5)

        # シナリオ間待機
        if si < len(TEST_SCENARIOS) - 1:
            print(f"\n  ⏳ シナリオ間待機 8秒...")
            time.sleep(8)

    print("\n" + "=" * 60)
    print(f"  全体結果: {'✅ 全PASS' if all_passed else '❌ FAILあり'}")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
