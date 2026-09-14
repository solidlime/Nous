# キャラチャット アバター品質改修 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## 実装状況（完了・検証済み）

全 Task 実装済み。検証は 2026-09-14 に実ブラウザ＋pytest で実施。**下の `- [ ]` は実装当時の指示書のまま残す**（未検証項目を完了扱いしないため、完了判定はこのブロックを正とする）。

| Task | 状態 | 根拠（実測） |
|---|---|---|
| 1 ログ比率スライダー＋永続化 | 完了 | 実ブラウザで操作し `--chat-log-h` が追従、リロード後も復元。`_task1_default_30pct.png` / `_task1_max_70pct.png` |
| 2 休息姿勢・待機・フレーミング | 完了 | `probe()`: `fallback:false` / `framing.fits:true`（visibleH 2.025 ≥ modelH 1.875）/ `armDropDeg` left 73.8° right 70.6° |
| 3 表情 UI | 完了 | `#chat-avatar-stage-ui` に表情セレクト＋強度スライダーが実表示（`_qa_vrma_final.png`） |
| 4 既定モデル解決 | 完了 | `tests/unit/test_avatar_model_resolution.py` が解決順を固定 |
| 6 VRMA 待機モーション | 完了 | `probe().motion === 'vrma'`, `vrmaBones: 21`。クリップ長 10.375 秒（GLB JSON から実測） |
| 5 総合検証 | 完了 | 下記 |

### 実装中に見つけて直した 3 件の重大不具合（記録）

1. **`#chat-avatar-stage-ui` が本番 HTML に存在しなかった** — dev harness (`_dev_probe_avatar.html`) にだけ手で置いていたため、本番ではログ高さスライダーと表情 UI が一切生成されなかった。`nous/api/http/sections/chat/chat_layout.py` の `render_chat_main()` に追加（`#chat-avatar-layer` の内側＝通常モードでは `display:none` で非表示）。増幅要因は「本番マークアップのテストが存在しないこと」だったため `tests/unit/test_chat_layout_markup.py` で要素の実在とネスト位置を固定した。
2. **VRMA のプロシージャル層が死んでいた** — `vrmaBones` を `vrm.humanoid.humanBones[].node`（**生の**ノード）で照合していたが、`createVRMAnimationClip` のトラック名は**正規化**ノード名（`Normalized_head.quaternion`）で、`AnimationMixer` の書込み先も正規化ノード。そのため集合が空になり乗算分岐が一度も実行されず、姿勢が VRMA の素の出力（腕を上げたまま）になっていた。正規化ノードを返す `nBone(name)` で照合するよう修正し、`probe().vrmaBones`（マッチ数）を追加してこの沈黙故障を可観測にした。
3. **base color texture が 1 枚も張られていなかった（「ほぼ真っ白」の真因）** — 実ブラウザ実測で、読み込み後の 35 材質すべてが `isMToonMaterial=true` / `color=#ffffff` / `shadeColorFactor=#797979` / `map=null`、`uniforms` 71 個にテクスチャが 1 つも無く、`parser.associations` にもテクスチャが 1 件も登録されていなかった。VRM 0.x の `_MainTex`(0/3/7/9) と glTF `pbrMetallicRoughness.baseColorTexture.index` は一致しており、`textures[15]` → `images[15]`（全て `image/png`、衣 2.0MB・髪 3.8MB 等）→ `bufferView` まで JSON 上は正しく繋がっている。**はっきりしているのは症状（`texture` 依存の解決が例外を出さず空を返す）と、同 parser の `bufferView` 経路が健全なことだけ**で、上流（three.js 本体／vendored `GLTFLoader`）がなぜ画像依存だけ解決に失敗するかは**未確定**。そこで `avatar.js` に `textureFromGlbImage()` を追加し、`bufferView`／`uri` から `createImageBitmap` でデコードして `material.map` に張る方式に切り替えた（`flipY=false` / `colorSpace=sRGB` / `texCoord` / sampler の wrapS・wrapT を反映。`KHR_texture_transform` が恒等でない場合は UV がずれるため**適用せず** `texDiag.issues` に記録する — herta.vrm は全材質 offset[0,0]・scale[1,1] の恒等を実測済み）。結果 `texDiag.bound=58, failed=0`、`texDiag.pixels={images:8, minNonWhitePct:82.7, maxNonWhitePct:100}` で、**白飛びが消えて衣装・帽子・髪・杖が正しい色で描画される**（`_qa_v2_textures.png`）。

**どの画像をどの材質へ張るかの決定は純ロジック側 `nous/api/http/static/chat/avatar/avatar-texture-plan.js` に分離した**（`avatar.js` 側は取得と代入のみ）。当初は材質名の文字列一致だけに依存しており、同名の複数材質・画像を持たない材質・既存 `map` 付き材質で誤結合し得た（さらに「その画像はどの材質も使っていない」という判定が手書き JSON を読む DOM 非依存テストとして書けなかった）。いまは材質ごとに `(画像添字, texCoord, sampler)` を確定し、同名が複数ある場合は**画像を持ち `map` がまだ null の材質だけ**に張る（herta.vrm は ` (Outline)` を除けば材質名が一意なので全件が同名解決でカバーされ、位置ベースのフォールバックは実行されない）。診断も実態に合わせて改名・追加した（`imageCount` = 画像あり材質数、`targets` = `map` が null で張り得る材質数、`bound` = 実際に張れた数、`sample.uv` = 使った UV セット、`issues` = 非恒等 transform 等の警告）。判定は `avatar-texture-plan.check.mjs`（`node` で実行・14 アサーション、`node:test` 非依存の自作 `assert` ハーネス）で固定した。

### 累積バグの再発否定（実測・60fps）

VRMA 乗算が毎フレーム累積していないことを実ブラウザで確認:

- 52 秒・52 サンプルの四分区間における t0 からの最大ずれ: spine 7.0 → 32.9 → 2.7 → 2.5°（Q3/Q4 が基準値へ戻る。累積なら増え続ける）
- 21.4 秒・107 サンプル（200ms 間隔）の**最小**ずれ: spine 0.22° / chest 0.08° / head 0.18° / leftUpperArm 0.08° / hips 0
- **最小ずれ ≈ 0 = 姿勢が繰り返し初期値へ戻る**。クリップ長 10.375 秒に対し 52 秒＝約 5 ループで発散しないことを確認
- 唯一 translation トラックを持つ `root`(→hips) も最大 2.82°・成長 0

### Task 5 の検証結果（実測）

- `python -m pytest tests/ -q` → **2636 passed, 1 skipped**（実装前 baseline 2634 + 追加テスト 2 件。回帰ゼロ）
- `python -m ruff check <変更 py ファイル>` → All checks passed / `ruff format --check` → already formatted
- `python -m mypy <変更 2 ファイル>` → **変更ファイルのエラー 0**（出力中の 345 件は全て他所の既存エラー。`pytest --cov` は 70.99% を実測済み）
- `node --check` → `avatar.js` / `chat-mode.js` とも通過
- 実ブラウザ: `motion:'vrma'` / `framing.fits:true` / `armDropDeg` 73.8, 70.6 / ログ高さ 30% 表示 / 表情 UI 表示

### 未検証・残存リスク

- 通常チャットモード（キャラモード OFF）のスクショは Task 1 検証時に取得済み（`_task1_normal_mode.png`）。ただし最終差分での再取得および**ピクセル差分による機械比較は未実施**（`#chat-avatar-layer[hidden] { display: none }` と `tests/unit/test_chat_layout_markup.py` のネスト検証で構造的に担保）。
- VRMA クリップの動作量（spine 最大 43°）はアセット固有。見た目は自然だが、より静かな idle が好みなら `animations/idle_loop.vrma` の差し替えのみで済む。
- **`KHR_texture_transform` が恒等でないモデルではベースカラーの UV がずれる**（本実装は適用せず `texDiag.issues` に記録するのみ）。`herta.vrm` は全材質が恒等なので実害は無い。
- `sampler.magFilter` / `minFilter` は写していない（three の既定が glTF の既定と一致するため）。`NEAREST` を明示するモデルでは見た目が変わり得る。
- `avatar-texture-plan.js` のテスト（`avatar-texture-plan.check.mjs`）は **JS 側のみで、CI からは実行されない**（手動 `node` 実行）。Python 側のテストと同じゲートには乗っていない。
- `herta.vrm` / `sample.vrm` は untracked のまま（再配布ライセンス未確認。Global Constraints の通り git に追加しない）。

**Goal:** キャラチャットモードの VRM アバターを「実用に耐える」水準へ引き上げる。具体的には (1) ログ/キャラの高さ比率をスライダーで変更＋永続化、(2) 待機モーション（呼吸・体重移動・腕の追従）と自然な休息姿勢（Y ポーズ脱却）、(3) VRM 内蔵の表情を選択できる UI、(4) カメラの自動フレーミングとトゥーン調リム表現。

**Architecture:** フロントは既存 3 ファイル（`avatar.js` = three.js/VRM 描画層、`chat-mode.js` = UI/配線層、`avatar.css` = キャラモード専用スタイル）に閉じる。レイアウトは `#chat-main.character-mode` に CSS 変数 `--chat-log-h` を 1 本導入し、`#chat-avatar-canvas-container` と `#chat-messages` が上下に分割して重ならないようにする（現状は両者が重なっているのが「ログエリア要調整」の正体）。バックエンドは `avatar_models.py` の既定モデル解決のみ変更（リポジトリ直下 `herta.vrm` → data_root のアップロード済みモデル → `prototype/sample.vrm` の順）。

**Tech Stack:** vanilla JS (ES modules, three.js 0.180.0 / three-vrm 3.5.5 を vendored) / Python 3.12 + FastAPI / pytest

## 実測した現状（真因）

- `nous/api/http/static/chat/avatar/avatar.css:97` — `#chat-main.character-mode #chat-messages` が `position:absolute; bottom:0; max-height:55%; background:rgba(10,8,20,0.55)`。一方 `#chat-avatar-layer` は `inset:0`（同 6 行目）で全面を覆う。**この 2 つが重なるため、キャラの胴体が半透明ログ越しに透けて見える。**
- `avatar.js` — カメラは `PerspectiveCamera(30, 1, 0.1, 50)` + `radius 2.6` 固定。距離 2.6m・縦 fov 30° → 可視高 `2*2.6*tan(15°) = 1.39m`。モデル高は bbox 実測 `0.00〜1.876m` なので**足元と頭が必ず切れる**。
- `avatar.js` — `A_POSE = { leftUpperArm:{z:-70}, rightUpperArm:{z:70} }` を正規化ボーンへ書き込むが、レンダリング結果は**腕を上げた Y ポーズ**（`_chat_mode_before.png` で視認）。正規化ボーンの局所軸はモデル（VRM0/1）依存で、z 軸への回転が「腕を下げる」方向に対応する保証がない。
- `avatar.js` — idle は `off.spine.z += D(1.5*sin(...)*0.1)` ≒ 0.15°、`head.x ≒ 0.8°`。**実質静止**で「待機モーションが無い」状態。
- `avatar.js` — `EMOTIONS = ['happy','surprised','sad','angry','relaxed','neutral']`。herta.vrm の expressionManager は VRM0 の 18 個（`neutral/aa/ih/ou/ee/oh/blink/happy/angry/sad/relaxed/lookUp/Down/Left/Right/blinkLeft/blinkRight/Toggle WP`）で **`surprised` は存在しない**。
- `avatar_models.py` — 一覧 API が空を返すため UI は `sample.vrm (default)` と表示するが、実際に配信されるのは `herta.vrm`。**表示と実体が乖離**。
- ~~モデルは正常に描画される（`_herta_shot_before.png` でテクスチャ・MToon とも正常）~~ → **誤り（2026-09-14 の実ブラウザ実測で否定）**。実ページでは 35 材質すべてで base color texture が未バインドで、モデルはほぼ白く描画されていた（詳細は上の「重大不具合 3」）。`_avatar_dev_1.png`(3.3KB 全白, 20:34:17) も同じ根因の症状だった。

## Global Constraints

- Windows。テストは `.venv\Scripts\python -m pytest <path> -q`
- lint: **変更したファイルに新規の ruff エラーを出さないこと**。`ruff check .` の既存 baseline は 28 件あり、内訳は `scripts/*.py`(SIM115/I001/B905) と `tests/unit/test_tts_*.py`(E402/I001/E731/E401/E702) のみで `nous/` には 1 件も無い。**これらの既存エラーは今回の作業で修正してはならない**（無関係な差分を混ぜない）。判定は「変更ファイルに新規エラーが無いこと」で行う。
- アバター関連の既存テストは存在しない（`pytest nous/ -q -k avatar` は collected 0）。`avatar_models.py` の既定モデル解決順は分岐を持つロジックなので、Task 4 では `tests/unit/test_avatar_model_resolution.py` を新規追加して解決順（herta.vrm 優先 → アップロード済み → sample.vrm フォールバック）を pytest で固定する
- 禁止操作: `git push --force` / `git commit --no-verify` / `DROP TABLE` / `DELETE FROM`
- コミットは conventional prefixes（日本語サブジェクト可）
- 検証は実ブラウザ。dev harness（`_tmp_static_server.py` + `_dev_chat.html`）を port 18100 で起動し `agent_browser` でスクショ＋DOM 読み出し
- UI 変更は実表示のスクリーンショット確認を完了条件に含める（テスト緑のみでは完了としない）
- `herta.vrm` は 30.8MB の untracked ファイル。**git に追加しない**（再配布ライセンス未確認）。存在しない環境では `prototype/sample.vrm` へフォールバックする

## インターフェース契約（両タスク共通・厳守）

`initAvatar(container, modelUrl)` が返す handle を次の形に固定する:

```js
{
  setExpression(name, weight),   // name は任意（存在しない名前は無視）。weight は 0..1 に clamp
  setTalking(on),
  setPose(name),
  playGesture(name),
  listExpressions(),             // { emotions:[...], mouths:[...], other:[...], auto:[...] }
  probe(),                       // 下記の診断オブジェクト
  dispose(),
  __vrm
}
```

`probe()` の戻り値（検証の機械判定に使う）:

```js
{
  fallback: boolean,               // true なら VRM ではなくフォールバック画像
  bones: { leftUpperArm: bool, rightUpperArm: bool, leftHand: bool },
  armDropDeg: { left: number, right: number },  // 水平からの下げ角（正=下がっている）
  framing: { visibleH, visibleW, modelH, modelW, fits: boolean },
  pose: string,
  idle: { breath: number, sway: number },       // 直近 1 秒の振幅（実測）
  expressions: { [name]: number },              // expressionManager の実値
}
```

---

## Task 1: ログ/キャラ比率スライダー＋レイアウト分離

**Files:**

- Modify: `nous/api/http/static/chat/avatar/avatar.css`
- Modify: `nous/api/http/static/chat/avatar/chat-mode.js`

- [ ] `#chat-main.character-mode` に `--chat-log-h: 30%` を定義する
- [ ] `#chat-avatar-canvas-container` を `inset: 0 0 var(--chat-log-h) 0`（= ログ分を除いた上側）に変更する。これでキャラとログが重ならなくなる
- [ ] `#chat-messages` の `max-height: 55%` を `height: var(--chat-log-h); max-height: var(--chat-log-h)` に変更する
- [ ] ログ最終行が入力エリア（絶対配置・z-index 12）に隠れないよう `#chat-messages` に十分な `padding-bottom` を入れる
- [ ] `#chat-avatar-stage-ui`（既存の空 div）に `<input type="range" id="chat-log-ratio">` と現在値ラベルを注入する。範囲 15〜70、既定 30
- [ ] `input` イベントで CSS 変数を即時更新し、`localStorage['nous.chat.logRatio']` に保存する。初期化時にその値を復元する
- [ ] 比率変更時に `#chat-avatar-canvas-container` のリサイズが走り、カメラが再フィットすること（Task 2 の ResizeObserver 経由でよい）
- [ ] スタイルは `avatar.css` に追記（`#chat-avatar-stage-ui` はステージ左下・glass 調。既存 `#chat-avatar-model-ui` の見た目に合わせる）

**検証:** dev harness でスクショ 2 枚（既定値 / スライダー最大）。キャラとログが重なっていないこと、リロード後も比率が保持されることを確認。

## Task 2: 休息姿勢の較正・待機モーション・カメラ自動フレーミング

**Files:**

- Modify: `nous/api/http/static/chat/avatar/avatar.js`

- [ ] **腕の較正（Y ポーズ脱却）**: 初期化時に左 `leftUpperArm` を x/y/z 各軸 ±0.3rad だけ試し回し、`leftHand` のワールド Y が最も下がる（軸, 符号）を選ぶ。右腕も同様に独立して較正する。結果は `probe().armDropDeg` に出す。ハードコードした `z:-70 / z:70` は廃止する
- [ ] 較正で選んだ軸に「水平から 70° 下げる」を休息姿勢として適用する（腕は体側へ）。前腕は肘の曲がりを崩さない範囲で自然に追従させる
- [ ] **待機モーション**: 呼吸（胸/脊椎の周期 4 秒・複数周波数の重ね合わせ）、体重移動（腰の水平移動＋脊椎の対傾斜）、肩の上下、頭の微動（2 つの異なる周期を重ねてループ感を消す）、腕の追従揺れを実装する。振幅は**目視で分かる大きさ**にする（現行の 0.15° は不可）。ジェスチャ/感情オフセットへの加算は既存の「毎フレーム基準から再構成する」方式（加算代入 `+=` 禁止）を維持する
- [ ] `probe().idle` で呼吸・揺れの実振幅を数値で返す（検証用）
- [ ] **カメラ自動フレーミング**: ロード後に `Box3.setFromObject` でモデルの bbox（y 高さ・x 幅）を実測し、縦 fov と横 fov の両方が収まる距離を計算して適用する。`camera.aspect` はリサイズのたびに更新されるため、`resize()` でも再フィットする
- [ ] wheel ズームは「自動距離 × 倍率」に変更する。倍率はユーザー操作でのみ変化し、自動フィットの再計算に上書きされないこと
- [ ] ドラッグ水平回転（azimuth）と `vrm.lookAt.target` の追従は現状維持
- [ ] **MToon の見た目調整**: 各 MToon マテリアルのリムライト系パラメータ（`parametricRim` / `rimLightingMix` / `parametricRimFresnelPower` 等）で控えめなリムを付ける。既存のテクスチャ・アウトラインを壊さないこと。過剰なら弱める
- [ ] `probe()` を実装する（上記契約）。`listExpressions()` は expressionManager の実在名を `emotions`（neutral/happy/angry/sad/relaxed）/ `mouths`（aa/ih/ou/ee/oh）/ `other`（Toggle WP 等）/ `auto`（blink*・look* = 自動制御なので UI に出さない）に分類して返す
- [ ] `setExpression` は任意名を受け付け、存在しない名前は無視する。`EMOTIONS` 定数による「実在しない名前を 0 で塗る」実装を実在名ベースへ直す
- [ ] `noopHandle()` にも `listExpressions` / `probe`（`fallback: true` を返す）を追加し、呼び出し側が分岐不要になるようにする

**検証:** dev harness の `probe()` 出力を DOM に流し、`agent_browser` で読み出して次を機械判定する — `fallback === false` / `bbox` の投影がステージ矩形内（`framing.fits === true`）/ `armDropDeg` が 50〜80° / `idle.breath > 0.01`。加えてスクショで目視確認。

## Task 3: 表情選択 UI

**Files:**

- Modify: `nous/api/http/static/chat/avatar/chat-mode.js`
- Modify: `nous/api/http/static/chat/avatar/avatar.css`

- [ ] `#chat-avatar-stage-ui` に表情セレクト（`#chat-avatar-expression`）と weight スライダー（`#chat-avatar-expression-weight`）を追加する
- [ ] 選択肢は `handle.listExpressions()` から生成し、`emotions` / `mouths` / `other` を `<optgroup>` で分ける。`auto`（blink・look*）は**出さない**
- [ ] 選択変更とスライダー操作で `handle.setExpression(name, weight)` を呼ぶ。weight は 0〜1
- [ ] 既定値は「なし（neutral）」。選択解除できること
- [ ] キャラモードを抜けたらセレクトを初期状態に戻す（既存の teardown に合わせる）

**検証:** dev harness で `happy` を選び `probe().expressions.happy > 0` を DOM から読み出して確認。他の表情が 0 のままであることも確認。

## Task 4: 既定モデル解決と一覧 API

**Files:**

- Modify: `nous/api/http/routers/chat/avatar_models.py`

- [ ] モデル解決順を「リポジトリ直下の `<repo>/herta.vrm` → data_root 配下のペルソナ別アップロードモデル → `prototype/sample.vrm`」にする
- [ ] 一覧 API が**実際に配信される既定モデル名**を返すようにし、UI のセレクトが `herta.vrm (default)` と正しく表示すること（現状は実体 herta.vrm なのに `sample.vrm (default)`）
- [ ] フォールバックした場合は `logging.warning` で理由を出す（黙って sample に落ちない）
- [ ] 既存のアップロード/選択 API の挙動を変えない

**検証:** `pytest nous/ -q -k avatar` ＋ dev harness でセレクト表示が実体と一致すること。

## 意図的に見送ったこと（記録）

- **カスタムシェーダ差し替え**: 既存 MToon はテクスチャ・アウトライン用マテリアルとも正常で、差し替えは表情・輪郭を損なうリスクの方が大きいため行わない。リムライトは MToon 自身のパラメータで表現する。

## Task 6: VRMA による待機モーション（追加要求・ユーザー承認済み）

**背景**: ユーザーから「VRMA を実装してほしい。ローカルで動かすだけの個人的なプロジェクトだし」と明示指示があった（m00257）。当初はライセンス帰属不明を理由に見送る計画だったが、個人ローカル利用かつリポジトリへコミットしない前提のため導入する。

**ファイル**:
- 変更: `nous/api/http/static/chat/avatar/avatar.js`
- 新規: `nous/api/http/static/chat/avatar/animations/idle_loop.vrma`（入手元は Task 6 手順 1）
- 新規: `nous/api/http/static/chat/avatar/vendor/three-vrm-animation.module.js`（npm 未インストールのため vendor 化。ただし**バンドラ無しで動く形に限る** — 下の「実装方式の制約」参照）

**手順**:
1. idle ループを取得する。第1候補 `https://raw.githubusercontent.com/ZaberKo/vrm-studio/main/public/animations/idle_loop.vrma`（157,664 bytes / HTTP 200 実測済）。失敗時は `collection2/Relax.vrma`（118,448 bytes）。`curl -sSL -o <path>` で取得し、**取得後にファイルサイズと先頭 4 バイトが `glTF` であることを検証する**（HTML の 404 ページを掴む事故を防ぐ）。
2. `@pixiv/three-vrm-animation` は**まず vendor せずに済む方法を探す**。`import { VRMAnimationLoaderPlugin, createVRMAnimationClip } from '@pixiv/three-vrm-animation'` は bare specifier なので、既存 vendor `three-vrm.module.js` の中に該当シンボルが含まれていないか確認する。含まれない場合のみ `three-vrm-animation` の ESM ビルドを取得し、**その内部 import も全て既存 vendor の相対パスに書き換える**（前回 `three-vrm.module.js` をバンドルするのに使ったのと同じ手法）。
3. 読み込み: `GLTFLoader` + `loader.register((parser) => new VRMAnimationLoaderPlugin(parser))` → `vrm.scene.add(...)` ではなく `vrm.humanoid` に `AnimationMixer(vrm.scene)` でクリップを適用（`createVRMAnimationClip(vrmAnimation, vrm)`）。

**実装方式の制約（重要・ここを外すと壊れる）**:
- 既存のポーズ書き込みは「絶対角を毎フレーム新規に再構成する」方式（累積加算なし）。VRMA の `AnimationMixer` がボーンを直接書き換えるため、**更新順を明示的に固定する必須**: `mixer.update(dt)` を**先に**実行し、その後でプロシージャル層（呼吸・体重移動）を**低速の追加層**として上書き合成する。プロシージャル層は VRMA 再生中は振幅を **半減**（例: 呼吸 3.0° → 1.5°）させ、VRMA と喧嘩しないようにする。
  ```
  mixer.update(dt);        // 1. VRMA が骨盤・背骨・胴体を動かす
  applyIdleLayer(ramp);   // 2. 呼吸/体重移動/頭の微動を加算的に上書き（振幅 ×0.5）
  vrm.humanoid.update();   // 3. スキン＋揺れ物
  ```
- VRMA 再生中は「休息姿勢の固定角」を適用しない（VRMA が腕の下げを担う）。`pose` が `neutral` 以外（wave/think/bow）のときのみ VRMA を一時停止し固定ポーズを優先する。
- VRMA が読み込めなかった場合は**必ずプロシージャル idle にフォールバック**し、`probe().motion` に `'procedural'` / `'vrma'` を入れ、`idle.breath` は VRMA 経路でも数値が動くこと。

**完了条件（機械判定・`probe()` 経由）**:
- `motion === 'vrma'`（VRMA 読み込み成功を意味する）
- `idle.breath > 0.01`
- `armDropDeg.left` と `right` が 50〜80°
- アーム下げ角: VRMA が腕を動かす場合があるため、判定は「ばらつき（左右差）< 5°」を主基準にする
- 既存 4 条件（`fallback===false`, `framing.fits===true`）を維持
- `node --check nous/api/http/static/chat/avatar/avatar.js` 通過
- プロシージャル fallback 経路も残すこと（`motion:'procedural'` を強制する手段を設ける）

**禁止**: `herta.vrm` の変更、コミット、既存 `vendor/three-vrm.module.js` の破壊的書き換え、ファイルサイズが 10MB を超えるアセットの取得。

## Task 5: 総合検証

- [ ] dev harness（port 18100）で before/after スクショを取得
- [ ] `.venv\Scripts\python -m pytest nous/ -q` と `ruff check .` が緑
- [ ] 通常チャットモード（キャラモード OFF）のレイアウトが一切変わっていないことをスクショで確認
