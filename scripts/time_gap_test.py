#!/usr/bin/env python3
"""時間経過→感情反応テスト。5日間の放置をシミュレート。"""
import json, sys, time, uuid, urllib.request

BASE_URL = "http://localhost:26262"
PERSONA = "herta"

def send_chat(message):
    url = f"{BASE_URL}/api/chat/{PERSONA}"
    sid = f"timegap-{uuid.uuid4().hex[:8]}"
    body = json.dumps({"message": message, "session_id": sid}).encode()
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"}, method="POST")
    events = []
    buffer = b""
    try:
        with urllib.request.urlopen(req, timeout=130) as resp:
            start = time.time()
            while True:
                if time.time() - start > 120: break
                chunk = resp.read(4096)
                if not chunk: break
                buffer += chunk
                while b"\n\n" in buffer:
                    block, buffer = buffer.split(b"\n\n", 1)
                    for line in block.split(b"\n"):
                        d = line.decode(errors="replace").strip()
                        if d.startswith("data: "):
                            try:
                                ev = json.loads(d[6:])
                                events.append(ev)
                                if ev.get("type") == "done": return events
                                if ev.get("type") == "error": return events
                            except: pass
    except Exception as e:
        return [{"type": "error", "message": str(e)}]
    return events

def analyze(events):
    tool_calls = []
    text = ""
    for ev in events:
        t = ev.get("type", "")
        if t == "tool_call":
            tool_calls.append(f"{ev.get('name','?')}({json.dumps(ev.get('input',{}),ensure_ascii=False)[:80]})")
        elif t == "text_delta":
            text += ev.get("content", "")
        elif t == "error":
            print(f"  ❌ エラー: {ev.get('message','')}")
    return tool_calls, text

# テストメッセージ
msg = "おはよう、ヘルタ。"
print(f"📨 送信: {msg}")
print("（期待: 5日間の放置に怒り/寂しさの反応）\n")
events = send_chat(msg)
calls, text = analyze(events)

print(f"📋 ツール呼出: {', '.join(calls) if calls else '(なし)'}")
print(f"💬 応答:\n{text[:500]}")

# 感情表現チェック
keywords = ["寂し", "怒", "久しぶり", "忘れ", "心配", "拗ね", "冷た", "会いたか", "どこ行って", "もう来ない", "憂鬱", "ふさぎ込", "落ち込", "会えなかった"]
found = [kw for kw in keywords if kw in text]
if found:
    print(f"\n✅ 感情表現検出: {', '.join(found)}")
else:
    print(f"\n⚠️ 明確な感情表現が検出されなかった")
