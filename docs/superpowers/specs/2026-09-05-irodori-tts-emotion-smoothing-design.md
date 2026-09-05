# Irodori-TTS 感情断絶解消 — スタイルアンカー固定 Design (2026-09-05)

## 背景・問題
- OFF (LLMキャプション無効, デフォルト): `routers/tts.py:132` が `joy80%\nRelationship:...\nAppearance:...` というメタデータダンプを caption に送る。Irodori-TTS が期待する自然文スタイル指示ではないため無視され、サーバー側チャンク (`chunking_enabled=True, chunk_min_chars=85`) 毎に本文語感からスタイル推測 → 発話内で「感情的→急に冷静」な漂流が発生。
- ON (LLMキャプション有効): ① system プロンプトに「読み上げテキスト自体の内容から感情を推測して良い」がありグローバル感情より本文が優先される ② `temperature=0.7` で同一感情でも毎回違う言い回し ③ 前回 caption の記憶なし → リクエスト毎に別人の声に聞こえる断絶が発生中。

## ゴール / 非ゴール
- ゴール: ON/OFF どちらでも (1) 発話内チャンク間の声質・トーン漂流を止める (2) リクエスト間の微変動による別人化を止める。
- 非ゴール: クライアント側文分割＋チャンク別合成＋結合 (重いので今回はやらない)。seed 固定の強制。話速マッピングの作り替え。

## アーキテクチャ
`routers/tts.py` のみに変更を閉じる。`irodori.py` (送信層) は無変更。

```
PersonaState(emotion, intensity, appearance, relationship)
  → build_style_anchor() : 決定的1文アンカー (OFF/ON共通土台)
  → OFF: anchor をそのまま caption として送信
  → ON : anchor を【固定条件】として LLM に渡し、本文は【参考(緩急・間のみ)】に格下げ。LLM出力にも anchor 継承＋一貫接尾辞を強制
  → 送信前: intensityバケット化＋前回captionキャッシュで微変動を吸収
```

## コンポーネント
1. `build_style_anchor(emotion, intensity, appearance, relationship) -> str` (新規純関数, `tts.py`)
   - `EMOTION_TONE_HINTS[emotion]` + 強度修飾 (`intensity<0.3` は「感情を抑えめに、穏やかな話し方で」) + 地の声 (`appearance`/`relationship` があれば短く付記) + 固定接尾辞「全体を通して一貫した声質・感情で話す。」で1文 (80文字目安) に組み立て。`emotion` 空なら地の声のみ。
2. OFF パス (`tts.py:130-139` 置換)
   - メタデータダンプ廃止 → `caption = build_style_anchor(...)` のみ。`cfg_scale_caption` 等の送信パラメータは変更なし。
3. ON パス (`tts.py:141-226` 修正)
   - `temperature 0.7→0.2`, `max_tokens 256→128`。
   - `llm_system` 書換: 「グローバル感情・アンカーが主。本文からの感情推測・切替は禁止。本文は緩急・間・息遣いの参考のみ。前回 caption の声質を維持し、感情が大きく変わった場合のみ寄せる。出力は自然な日本語1文、必ず一貫接尾辞で締める。」
   - `llm_user` 分離: `【固定条件】{anchor + emotion/intensity}` / `【前回】{prev_caption or なし}` / `【参考本文(感情決定に使わない)】{text}`。
   - 生成結果が空/失敗 → OFF アンカーにフォールバック (既存 except 流用)。
4. なめらか化 (TTSルーター内インメモリ)
   - `intensity` を 0.1 刻みでバケット化 (`round(intensity + 1e-9, 1)`)。`_LAST_CAPTION: dict[str, tuple[str, float, str]]` (persona → (emotion, bucket, caption)) を保持。`(emotion, bucket)` が同一なら caption 再生成せず再利用 (ON の LLM 呼び出し自体をスキップ)。キャッシュキー (`_tts_cache_key`) には影響させない (音声キャッシュ爆発防止)。
   - プロセス再起動で消える揮発性でよい (永続化しない)。

## データフロー
1. POST `/api/tts/{persona}` (body: text のみ、emotion は送らない — 従来通りサーバー側解決)。
2. `voice_emotion_link` が ON なら `PersonaState` 取得 → anchor 構築。
3. OFF: 即送信。ON: バケット一致なら前回 caption 再利用、不一致のみ LLM 生成。
4. `engine.synthesize(text, emotion, caption, speed)` → 音声キャッシュ (`text|emotion|caption|...` 既存キー) → 返却。

## エラーハンドリング
- LLM 失敗・空出力 → OFF アンカーで合成継続 (無音・500 にしない。ただし合成自体の失敗は従来通り 500)。
- `emotion` 不正値 → `EMOTION_TONE_HINTS.get` フォールバック「「{emotion}」の感情に合った話し方で」。
- スレッドセーフ: `_LAST_CAPTION` は単純 dict + GIL 依存でよい (厳密なロックは不要)。

## テスト
- `tests/unit/test_tts_style_anchor.py` (新規):
  - anchor が1文・接尾辞「全体を通して一貫した声質」含むこと。`intensity<0.3` で抑えめ文言になること。`emotion=""` で破綻しないこと。
  - ON プロンプト組み立てが「感情切替禁止」「本文は参考のみ」を含むこと。合成呼び出し側が `temperature=0.2, max_tokens=128` で呼ぶこと。
  - バケット化: `round(0.82 + 1e-9, 1)==0.8` で微変動時に再生成しないこと。
- 既存: `pytest tests/unit/test_tts_emotion_caption.py -v` が green のまま (build_caption_emotion_directive は残すか、anchor に統合する場合はテスト更新)。

## 移行・互換
- 設定項目の追加なし。`irodori_caption_llm_enabled` の意味はそのまま。
- OFF の caption 文面が変わるため、既存 `tts_cache/*.wav` とのハッシュ不一致で初回のみ再生成 (自然消滅、問題なし)。
- `EMOTION_TONE_HINTS` / `build_caption_emotion_directive` は残す (anchor が内包利用)。

## リスク
- caption を強くすると抑揚の幅が狭まる (意図通りだが、物足りなければ `cfg_scale_caption` を 4.2→3.5 方向で後調整)。
- プロセス内キャッシュのため多ワーカー時はワーカー毎に別 caption (実害は軽微)。
