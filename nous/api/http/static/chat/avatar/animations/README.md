# 待機モーション (VRMA)

## idle_loop.vrma

- 出所: <https://github.com/ZaberKo/vrm-studio> (`public/animations/idle_loop.vrma`)
- ライセンス: MIT License (Copyright (c) ZaberKo) — 帰属表示のため出所を明記する
- 形式: glTF binary + `VRMC_vrm_animation` 拡張 (specVersion 1.0)。長さ 10.375 秒、humanoid 22 骨。
  `translation` チャンネルは `hips` のみで、他は `rotation` のみ。

`avatar.js` が読み込み、プロシージャル層 (呼吸・重心移動・腕の自然な垂れ・瞬き) と乗算合成する。
差し替える場合は同じパスに置くだけでよい (ファイル名は `avatar.js` の既定 URL、
または要素の `data-avatar-vrma-url` で上書き可能)。ファイルが無い場合はプロシージャル動作のみに自動フォールバックする。
