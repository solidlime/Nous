"""ペルソナディレクトリの移行状態を読むだけの点検ツール（書き込みなし）。

    python scripts/check_persona_layout.py [data_root]

人ごとに「新レイアウトが揃っているか」「旧レイアウトの残骸が残っていないか」を出す。
移行そのものはサーバー起動時に migrate_persona_layout() が走る。ここはその結果を
目で確認するためのもの。sandbox に見えてよいのは media / wiki / uploads / workspace
だけで、db と config.json は見せない。
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ から nous を import できるようにする（インストール無しで走らせる）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nous.infrastructure.persona_layout import _LEGACY_GLOBS, _MOVES, persona_db_dir  # noqa: E402

# 新レイアウトで sandbox に見せるもの。無くてもエラーではない（使えばできる）。
_VISIBLE = ("media", "wiki", "uploads", "workspace")


def _leftovers(persona_dir: Path, data_root: Path) -> list[str]:
    found: list[str] = []
    for old_name, _sub in _MOVES:
        if (persona_dir / old_name).exists():
            found.append(old_name)
    named_db = persona_dir / f"{persona_dir.name}.db"
    if named_db.exists():
        found.append(named_db.name)
    for pattern in _LEGACY_GLOBS:
        found.extend(Path(p).name for p in sorted(persona_dir.glob(pattern)))
    if (data_root / "uploads" / persona_dir.name).is_dir():
        found.append(f"uploads/{persona_dir.name}/ (グローバル)")
    return found


def main() -> int:
    data_root = Path(sys.argv[1] if len(sys.argv) > 1 else "./data").resolve()
    persona_root = data_root / "persona"
    if not persona_root.is_dir():
        print(f"ペルソナディレクトリが無い: {persona_root}")
        return 1

    print(f"data_root = {data_root}\n")
    problems = 0
    for persona_dir in sorted(p for p in persona_root.iterdir() if p.is_dir()):
        name = persona_dir.name
        db = Path(persona_db_dir(data_root, name)) / "memory.sqlite"
        leftovers = _leftovers(persona_dir, data_root)
        visible = [d for d in _VISIBLE if (persona_dir / d).is_dir()]

        if not db.exists():
            state = "DB なし"
            problems += 1
        elif leftovers:
            state = "残骸あり（起動すれば移る/隔離される）"
            problems += 1
        else:
            state = "ok"

        print(f"[{state}] {name}")
        print(f"    db      : {'あり' if db.exists() else 'なし'}")
        print(f"    見せる枠 : {', '.join(visible) or '(なし)'}")
        if leftovers:
            print(f"    残骸     : {', '.join(leftovers)}")
        print()

    print("問題なし" if problems == 0 else f"{problems} 人に確認点あり")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
