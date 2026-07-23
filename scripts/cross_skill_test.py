#!/usr/bin/env python3
"""クロススキル全連鎖テスト — 全6パターン
prompt.py <cross_skill> マトリクスの全チェーンを検証。
モデル: openrouter/free
"""

import json, sys, time, urllib.request
from typing import Any

BASE_URL = "http://localhost:26262"
PERSONA = "herta"

TEST_CASES = [
    {
        "id": "auto→recall",
        "message": "週末はいつも山登りに行ってるんだよね。そういえば、前にどこかの山の話しなかったっけ？",
        "expect_primary": ["memory_create"],
        "expect_chain": ["memory_search"],
        "desc": "auto-memory発動 → recall-weaver連鎖",
    },
    {
        "id": "recall→auto",
        "message": "前に話したあのプロジェクトの話、覚えてる？大事な教訓があったはずなんだけど…",
        "expect_primary": ["memory_search"],
        "expect_chain": ["memory_create"],
        "desc": "recall-weaver発動 → auto-memory連鎖",
    },
    {
        "id": "mood→image+auto",
        "message": "今日すごく嬉しいことがあったんだ！プロジェクトが大成功して、すごく興奮してる。それでね…今の私、どんな感じに見えるかな？",
        "expect_primary": ["update_context"],
        "expect_chain": ["image_generate", "memory_create"],
        "desc": "mood-sync発動 → image-gen+auto-memory連鎖",
    },
    {
        "id": "goal→auto",
        "message": "来月から毎朝5時に起きてジョギングすることにしたんだ。健康のために絶対続ける！",
        "expect_primary": ["goal_manage"],
        "expect_chain": ["memory_create"],
        "desc": "goal-coach発動 → auto-memory連鎖",
    },
    {
        "id": "image→auto",
        "message": "ねぇ、今の私ってどんな雰囲気？ちょっと照れてるかも…見せてくれる？",
        "expect_primary": ["image_generate"],
        "expect_chain": ["memory_create"],
        "desc": "image-gen発動 → auto-memory連鎖",
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
                    try:
                        event = json.loads(decoded[6:])
                        events.append(event)
                        if event.get("type") in ("done", "error"):
                            return events
                    except json.JSONDecodeError:
                        pass
    return events


def send_chat(message: str, session_id: str) -> list[dict]:
    import uuid
    sid = f"cross-{uuid.uuid4().hex[:8]}"
    url = f"{BASE_URL}/api/chat/{PERSONA}"
    body = json.dumps({"message": message, "session_id": sid}).encode("utf-8")
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


def analyze(events: list[dict]) -> dict:
    """全ツール呼び出しを名前ベースで収集。invoke_skill 経由も考慮。"""
    tools = set()
    tool_details: list[dict] = []
    text = ""
    error = None
    for e in events:
        t = e.get("type", "")
        if t == "tool_call":
            name = e.get("name", "")
            inp = e.get("input", {})
            if name == "invoke_skill":
                # スキル経由の場合は、実際に呼ばれたスキル名を記録
                skill_name = inp.get("name", "")
                if skill_name == "auto-memory":
                    tools.add("memory_create")
                elif skill_name == "recall-weaver":
                    tools.add("memory_search")
                elif skill_name == "mood-sync":
                    tools.add("update_context")
                elif skill_name == "goal-coach":
                    tools.add("goal_manage")
                elif skill_name == "image-gen":
                    tools.add("image_generate")
                tool_details.append({"name": f"invoke_skill({skill_name})", "input": inp})
            else:
                tools.add(name)
                tool_details.append({"name": name, "input": inp})
        elif t == "text_delta":
            text += e.get("content", "")
        elif t == "error":
            error = e.get("message", "")
    return {"tools": tools, "details": tool_details, "text": text, "error": error}


def main():
    print("=" * 60)
    print("  クロススキル全連鎖テスト")
    print(f"  モデル: openrouter/free")
    print("=" * 60)

    passed = 0
    total = len(TEST_CASES)

    for i, tc in enumerate(TEST_CASES):
        print(f"\n▶ テスト {i+1}/{total}: [{tc['id']}] {tc['desc']}")
        print(f"  📨 {tc['message'][:80]}...")

        events = send_chat(tc["message"], "cross-test")
        result = analyze(events)

        if result["error"]:
            print(f"  🔴 エラー: {result['error']}")
            continue

        primary_ok = any(p in result["tools"] for p in tc["expect_primary"])
        chain_ok = all(c in result["tools"] for c in tc["expect_chain"])

        # 表示
        p_mark = "✅" if primary_ok else "❌"
        c_mark = "✅" if chain_ok else "❌"
        print(f"  Primary: {p_mark} {tc['expect_primary']} → called: {sorted(result['tools'])}")
        print(f"  Chain:   {c_mark} {tc['expect_chain']}")
        if result["details"]:
            calls = [f"{d['name']}" for d in result["details"]]
            print(f"  📋 {', '.join(calls)}")
        if result["text"]:
            print(f"  💬 {result['text'][:120]}...")

        if primary_ok and chain_ok:
            print(f"  🟢 PASS: 完全連鎖成立")
            passed += 1
        elif primary_ok:
            print(f"  🟡 PARTIAL: 主ツール発動、連鎖未確認")
        else:
            print(f"  🔴 FAIL: 主ツール未発動")

        if i < total - 1:
            print(f"  ⏳ 8秒待機...")
            time.sleep(8)

    print(f"\n{'='*60}")
    print(f"  結果: {passed}/{total} 完全連鎖成立")
    print("=" * 60)
    return 0 if passed >= 3 else 1


if __name__ == "__main__":
    sys.exit(main())
