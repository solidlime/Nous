# TTS 文分割ストリーミング再生＋結合 Design (2026-09-05)

## 背景・問題
- 現状は `chat-send.js:done` 後に全文1発 `POST /api/tts/{persona}` (`chat-tts.js:autoPlayTts:257`)。長文ほど初音が遅く、`timeout_seconds=30` (`settings.py:190`) に当たりやすい。
- サーバ内チャンク (`irodori.py:chunking_enabled=True, chunk_min_chars=85`) はサーバ内処理で、クライアントは恩恵を受けない。全文確定待ち＋全文1合成がボトルネック。
- 要望: 文ごとに irodori へ投げてストリーミング風に再生、音声は保存し、最終的に1ファイルに結合してシークバー再再生したい。通常チャット自動再生と長文読み上げの両方で使いたい。

## ゴール / 非ゴール
- ゴール: (1) 初音高速化（1文目確定→即合成→即再生）(2) 文キャッシュ再利用 (3) 結合wavを全文キーで `tts_cache` 保存し単一シークバーで再再生。
- 非ゴール: SSE新設、mp3対応、DLボタン、感情/captionロジック変更、既存一発パスの廃止。新規依存追加なし（標準 `wave` のみ）。

## アーキテクチャ
フロント分割＋既存EP再利用＋サーバ結合（方式A）。

```
[SSE text_delta] streamedText蓄積
  → 文確定ごとに POST /api/tts/{persona} {text: sentence}（既存EP、文キャッシュ）
  → {audio_url} をキュー → Audio連鎖再生（先読み最大2）
[done] 残文flush → POST /api/tts/{persona}/combine {files, fullText}
  → wave結合 → tts_cache/{fullHash12}.wav → {ok, audio_url}
  → dataset.ttsCacheUrl上書き → 単一シークバーで再再生
```

`irodori.py` 送信層は無変更。`tts.py` に結合EP＋waveヘルパーのみ追加。`chat-tts.js` は無変更で `chat-tts-stream.js` を新設。

## コンポーネント
1. 文分割 (`chat-tts-stream.js` 新設、`splitSentences(text) -> string[]`)
   - 本命: `Intl.Segmenter(undefined, {granularity: "sentence"})`。`navigator.language` 追従、日英中混在対応。言語不問でサーバは無関与。
   - ガード: 20字未満は次文へマージ、200字超は `、。,` で硬分割。空文は除去。
   - フォールバック: `Intl.Segmenter` 不在時のみ正規表現（`。！？!?…`＋`.!?`の後に空白＋大文字＋改行保持）。
2. 再生キュー (`chat-tts-stream.js`、`StreamingTtsPlayer`)
   - 状態: `{queue: string[], pending: Map<seq, audioUrl>, playingSeq, audio: HTMLAudioElement | null, stopped}`。
   - 逐次POST（最大2並列先読み、順序再生）。到着順ではなく文順に再生。1文目到着で即 `new Audio(url).play()`。
   - 再生中UI: 「n文目再生中」表示＋停止ボタンのみ。シークバーは作らない（結合後に1本）。
   - 既存 `_playbackSession` と競合したら `_endSession("stream-start")` で単一化。`chat-voice-enabled` OFF・再生中重複・Abortは既存 `autoPlayTts` と同等に扱う。
   - フック: `chat-send.js` の `text_delta` 蓄積部で確定文をコールバック、`done` でflush＋combine呼び出し。
3. 結合EP (`tts.py` 追加、`POST /api/tts/{persona}/combine`)
   - 入力: `{files: string[], fullText: string, voice?: string}`。`files` は文合成時に返った `audio_url` のfilename部（`{hash12}.wav`）。件数上限50、1件あたり `..` 除去＋`.wav` 強制＋`_PERSONA_PATTERN` 検証（既存cache配信と同一）。
   - 処理: 各wavを `wave.open` でparams取得→全件一致検証（channels/sampwidth/framerate）→フレーム連結→全文キー（`_tts_cache_key(text=fullText, emotion=combine時点のstate解決, caption=combine時点解決, speed, voice)`）で `tts_cache/{fullHash12}.wav` に保存。文合成時とcombine時でemotion/captionがずれても結合音声自体は正当で、キーは再利用のためのみとする。
   - 出力: `{ok: true, audio_url}` のみ（base64なしで軽量化）。既存 `GET cache/{filename}` で配信。
   - `health_check` は結合時に1回のみ（文合成時は既存通り毎回だが、連続POSTの1RTT増は許容）。
4. waveヘルパー (`tts.py` 内、`_concat_wav(files: list[Path]) -> bytes`)
   - 標準 `wave` のみ使用。params不一致→ `ValueError` → EPは422返却。空リスト→400。

## データフロー
1. `text_delta` 受信→`streamedText`追加→`splitSentences`で確定文抽出→未送信文を `POST /api/tts`（文単位で既存キャッシュHIT可）。
2. 文音声到着→キュー→文順に `Audio` 再生（次文先読み継続）。
3. `done`→残文flush→全送信完了待ち→`POST /combine {files, fullText}`→結合wav保存。
4. `msgEl.dataset.ttsCacheUrl = combinedUrl` に上書き→単一 `Audio(combinedUrl)`＋既存 `_setupAudio` 流用でシークバー再再生可能に。
5. 手動🔊ボタン (`playTts`) は従来通り。`dataset.ttsCacheUrl` が結合URLなら結合音声を即再生。

## エラーハンドリング
- 文合成失敗: その文をスキップ継続、warnのみ。キュー全体は止めない。
- 文params不一致・結合失敗（422/500）: キュー再生は残す。`dataset.ttsCacheUrl` は上書きせず、結合なしでも聞き返しは文単位で可能。
- `files` 不正・空・上限超え: 400。存在しないファイル混入: 404相当の400（結合中断、部分結合は返さない）。
- Abort/停止: `AbortController` で未発リクエスト破棄、再生中Audio停止、`_endSession` で後片付け。

## テスト
- `tests/unit/test_tts_sentence_stream.py`（新規、バックエンド側）: `_concat_wav` がsine合成wavの連結でframes加算・params維持すること、不一致で `ValueError`、空で400相当に倒せること。`combine` のキー計算が `_tts_cache_key(fullText)` と一致すること。
- フロント: `splitSentences` の境界テスト（日英中混在・短文マージ・長文分割・フォールバック正規表現）。既存ブラウザ確認は `agent-browser` で初音latency目視（自動テストの成功のみで完了としない）。
- 既存: `pytest tests/unit/test_tts_*.py` がgreenのまま。`ruff`/`mypy` 新規0。

## 移行・互換
- 既存 `POST /api/tts` の入出力・キャッシュ形式・DELETE cleanupは無変更。文キャッシュは既存キー流用のため再利用される。
- 結合ファイルは全文キーで保存されるため、従来の一発合成結果と同一キーに収束する（初回のみ再生成）。
- `chat-tts.js:autoPlayTts` は残し、有効時はストリーミングを優先する。切替は `chat-voice-streaming` checkbox（デフォルトON、OFF時は従来の一発 `autoPlayTts`）。`Intl.Segmenter` 不在でもOFFには倒さず正規表現フォールバックで継続する。

## リスク
- リクエスト数増（文数分）。先読み2に制限し、文キャッシュHITで緩和。それでも長文連打時はサーバ負荷が上がる。
- 文間ギャップ（Audio要素切替のため無音数十ms）。gapless再生は狙わない（許容）。
- `Intl.Segmenter` のロケール差で切り方が環境依存。ガード（20/200字）で吸収するが、完全一致は保証しない。
