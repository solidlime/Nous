#!/usr/bin/env python3
"""Nous テスト実行スクリプト"""
import subprocess
import sys


def main():
    args = sys.argv[1:] or ["-v"]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/"] + args,
        cwd="D:/VSCode/Nous",
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
