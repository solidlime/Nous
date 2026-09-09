"""herta 記憶のタグ検索（デバッグ用）。使い方: python scripts/list-memories.py [tag] [limit]"""
import sqlite3
import sys

tag = sys.argv[1] if len(sys.argv) > 1 else "reflection"
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 15

c = sqlite3.connect(r"D:\Code\Nous\data\persona\herta\memory.sqlite")
rows = c.execute(
    "SELECT key, substr(content,1,70), tags, importance FROM memories WHERE tags LIKE ? ORDER BY updated_at DESC LIMIT ?",
    (f"%{tag}%", limit),
).fetchall()
for key, content, tags, imp in rows:
    print(f"{key}\n  [{imp}] tags={tags}\n  {content}")
print(f"total: {len(rows)}")
