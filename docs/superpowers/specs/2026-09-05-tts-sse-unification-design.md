# TTS SSE単一化 設計書

日付: 2026-09-05 / 状態: 承認済み（ユーザーOK）

## Goal

文ごとPOSTをやめ、1リクエスト＋SSE中継に一本化して初音を早める。
サーバの同時合成1本キューとの相性を正し、N往復・自己渋滞を消す。

## 非目標

- サーバ運用改善（PRELOAD/warmup/bf16/ref-latent）は対象外。管理者作業。
- num_steps/CFG等の品質チューニングは対象外（現行値維持）。
- 旧一括autoPlayの廃止はしない（フォールバックとして残す）。

## Architecture

```
[turn start] chat SSE開始 ──→ 字幕LLM並列タスク開始（personaスロットのFuture、感情は確定済み）
[chat done]  POST /api/tts/{p}/stream {text全文}
               ├─ 字幕Futureを待つ（大抵完了済み。失敗/タイムアウト→anchor後退）
               ├─ 全文strip（_stripMarkdown相当をサーバで1回）
               ├─ POST irodori /v1/audio/speech {stream_format:sse, first_sentence_chunk_min_chars:1, ...}
               └─ StreamingResponseで中継：event毎に audio_chunk(base64完結wav) をそのまま転送
[browser]    チャンク到来順にBlob再生（volume適用）＋ end で msgEl.dataset.ttsCacheUrl = 結合audio_url
[server]     中継しながらチャンク蓄積 → 完了時に _concat_wav → 全文キーでcache → 最終event{audio_url}
```

## 決定事項（ユーザー承認済み）

1. 字幕LLMは本文ストリーミングと並列化する。失敗時はanchorに後退。
2. 🔊再再生はサーバ結合・維持（結合wavを全文キーcache、今と同じURL再生UX）。
3. 途中切断は「来た分まで鳴らし、結合できた分だけ🔊に残す＋console警告」。全体リトライなし。
4. SSE不可時のみ旧一括autoPlayに後退。

## 廃止・削除

- 文ごとPOST経路、文キャッシュ（孤児化・自然淘汰、削除コードなし）。
- `POST /combine`（中継内結合に吸収）。
- フロント文分割・キュー（`splitSentences`ごと削除。stripはchat-tts.js側の旧経路用に残す）。
- チェックボックスID `chat-voice-streaming` は維持（ラベル文言のみ更新可）。

## 残すもの

strip（サーバで全文に1回）/ volume / 話速 / 音色 / resolve-once感情 / 結合キャッシュキー（旧結合エントリと等価のため版上げなし）。

## タイミング（正直な注記）

- 合成開始はdone時（全文が必要）。「文確定で投げて本文と並走」の重なりは失う。
- 初音 ≒ 字幕残り（並列でほぼ0）＋ 1チャンク合成。短文の体感差は小さい。中〜長文で効く。

## Error handling

| 事象 | 振る舞い |
|---|---|
| 字幕LLM失敗/タイムアウト | anchor後退、合成続行 |
| 中継途中切断 | 到来分まで再生、結合分のみcache＋警告 |
| SSE非対応/中継失敗 | 旧一括autoPlayに後退 |
| 空全文/strip後empty | リクエストなし（沈黙、警告のみ） |

## Testing

- Backend：irodori-SSEのmock中継テスト（順序・結合・cache・字幕成否分岐・切断時部分結合）。
- Frontend：チャンク再生キューのハーネス（volume適用・stop・失敗時）。
- 既存pytest TTS全セット維持。カバレッジ≥60%、lint0、型pass（GATE式は踏襲）。

## Rollout

1. バックエンド中継＋並列字幕 2. フロント書換 3. 旧経路削除 4. TEST→REVIEW(#081)→GATE→COMMIT→RECORD。
実ブラウザ確認はユーザー側（初音・🔊・失敗時）。
