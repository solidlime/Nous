"""リフレクション記憶の last_consumed_at / valid_until を確認。
使い方: python scripts/check-consumed.py
"""
import sqlite3

c = sqlite3.connect(r"D:\Code\Nous\data\persona\herta\memory.sqlite")
rows = c.execute(
    "SELECT key, last_consumed_at, valid_until FROM memories WHERE tags LIKE '%\"reflection\"%' ORDER BY updated_at DESC"
).fetchall()
for key, consumed, valid_until in rows:
    print(f"{key}  consumed={consumed}  valid_until={valid_until}")
print(f"total: {len(rows)}")
