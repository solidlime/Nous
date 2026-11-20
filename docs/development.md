
## pi-lens の mypy 誤帰属（既知・無視してよい）

`nous/application/chat/pipeline/inference.py` など、**触っていないファイル**に対して
「208 issue(s) must be fixed」が出続けることがある。pi-lens 同梱の mypy ランナーが
プロジェクト全体の mypy 出力を直近に開いた 1 ファイルへ帰属させるためで、
実際にはそのファイルに誤りは無い。

判断は必ず次の2つで行う（2026-11-19 に3通りで確認済み）。

```
make typecheck
.venv/bin/mypy nous/application/chat/pipeline/inference.py   # → Success: no issues found
```

`new: 0` なら CI の typecheck は通る。`[tool.mypy-baseline] allow_unsynced = true` を
入れているので、既存違反を直した（fixed）だけでも CI は落ちない。
