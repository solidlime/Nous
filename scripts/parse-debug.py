"""debug_info SSE を抽出して memories_raw / memory_queries を要約表示する。
debug_info はフラット構造: {"type": "debug_info", "memories_raw": [...], ...}
使い方: python scripts/parse-debug.py %TEMP%\\opencode\\probe1.events
"""
import json
import sys

def main():
    path = sys.argv[1]
    debug = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith("data: "):
                continue
            try:
                evt = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if evt.get("type") == "debug_info":
                debug = evt  # last one wins

    if not debug:
        print("NO debug_info event found")
        return

    data = debug  # flat payload
    for q in data.get("memory_queries", []):
        print(f"QUERY: {q}")
    for m in data.get("memories_raw", []):
        score = m.get("score", "?")
        tags = ",".join(m.get("tags", []))
        content = (m.get("content", "") or "")[:80].replace("\n", " ")
        print(f"MEM [{score}] ({tags}): {content}")
    cs = data.get("context_summary", "")
    if cs:
        print("--- context_summary (first 400):", cs[:400].replace("\n", " | "))
    print("=== assistant (first 200):", (data.get("assistant_response") or "")[:200].replace("\n", " "))

if __name__ == "__main__":
    main()
