"""probe events の system_prompt から直注入経路の痕跡を確認する。
使い方: python scripts/dump-section.py <events.file>
"""
import json
import sys

path = sys.argv[1]
for line in open(path, encoding="utf-8", errors="replace"):
    if not line.startswith("data: "):
        continue
    try:
        e = json.loads(line[6:])
    except json.JSONDecodeError:
        continue
    if e.get("type") != "debug_info":
        continue
    sp = e.get("system_prompt", "")
    idx = sp.find("最近の洞察")
    print("最近の洞察(t3):", "FOUND" if idx >= 0 else "NOT FOUND")
    if idx >= 0:
        print(sp[idx : idx + 400])
