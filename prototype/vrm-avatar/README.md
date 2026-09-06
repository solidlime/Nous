# VRM Avatar Prototype

スタンドアロンの VRM アバタープロトタイプ。nous 本体 (nous/api/http) とは無関係。

@pixiv/three-vrm で VRM1 モデルを読み込み、まばたき・呼吸 (spine の微小揺れ)・3秒周期の表情サイクル (happy → surprised → sad → angry → relaxed → neutral) をプロシージャルに再生する。依存は `three@0.180.0` と `@pixiv/three-vrm@3.5.5` のみで、bundler なしのバニラ ESM + importmap。ライブラリ実体は `vendor/` に同梱済み。

## 起動

```
cd prototype/vrm-avatar
python -m http.server 26270
```

http://localhost:26270/ を開く。

## モデル

`models/sample.vrm` は [vrm-c/vrm-specification](https://github.com/vrm-c/vrm-specification) の Seed-san サンプル (VRM 1.0, by VirtualCast, Inc.)。ライセンス: [VRM Public License 1.0](https://vrm.dev/en/licenses/1.0/index)。約 10.9MB。

## デバッグ

コンソールから `window.__avatarState` で `{ vrm, mixer, expressionManager }` にアクセス可能。
