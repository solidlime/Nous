# HANDOFF - TA03: Dynamic Temperature pipeline integration

## 完了したタスク

### TA03: EmotionDrivenSampler → Pipeline orchestrator ✅
| タスク | 内容 | 状態 |
|--------|------|------|
| TA03a | Orchestrator (ChatService.chat) が `turn_ctx.state_raw` から感情取得 → `EmotionDrivenSampler.compute()` → `effective_temp` 注入 | ✅ |
| TA03b | InferenceStep.run() に `effective_temp` パラメータ追加、provider.stream() で使用 | ✅ |
| TA03c | 統合テスト5件追加 (effective_temp差、fallback、stream伝搬、sampler計算) | ✅ |

## 変更ファイル一覧
| ファイル | 変更 |
|----------|------|
| `nous/application/chat/pipeline/inference.py` | run() に effective_temp パラメータ追加、provider.stream で使用 |
| `nous/application/chat/service.py` | dynamic_temperature=True 時のみ effective_temp 計算・注入 |
| `tests/unit/test_chat_pipeline.py` | TestDynamicTemperatureInference クラス追加 (5 tests) |
| `.spec/TODO-v3.md` | TA03 完了マーク |
| `.agent/memory/MEMORY.md` | TA03 学習記録追加 |

## 設計判断
- InferenceStep は PersonaState を直接参照しない — オーケストレータが `turn_ctx.state_raw` から emotion/intensity を抽出して計算
- `dynamic_temperature=False` 時は `effective_temp=None` を渡し、InferenceStep 内で `config.temperature` にフォールバック
- `turn_ctx.state_raw` は PrepareStep で既に設定済みなので、追加のサービス呼び出し不要

## テスト結果
- **test_chat_pipeline.py**: 56 passed (うち5件が新規温度テスト)
- **test_sampling.py**: 19 passed
- **test_chat_service.py**: 58 passed (うち7件が温度関連)
- **ruff check**: 0 errors on modified files

## 注意点
- 今回 `turn_ctx.state_raw` から emotion/intensity を取得しているが、`state_raw` は `vars(state)` の dict 変換なのでキー名は PersonaState のフィールド名に依存
- TA04 (WebUI設定) は未着手。dynamic_temperature トグル + scale スライダー + top_p 追加が必要
