/* =================================================================
   VRM avatar module for character mode.
   Exports initAvatar(container, modelUrl) -> Promise<handle>.

   handle = {
     setExpression(name, weight), setTalking(on), setPose(name),
     playGesture(name), listExpressions(), probe(), dispose(), __vrm
   }
   WebGL unavailable / load failure → static fallback in container,
   promise still resolves (no-ops) so callers never need error paths.

   設計メモ:
   - 腕の休息姿勢はハードコードせず、初期化時に「どの局所軸で回すと
     手首のワールド Y が最も下がるか」を実測して決める（正規化ボーンの
     局所軸はモデル依存のため、z 軸回転が下げ方向の保証がない）。
   - idle は毎フレーム「基準姿勢 + 時間依存オフセット」を再構成して
     絶対代入する。ボーン回転への加算代入（+=）は一切使わない。
   ================================================================= */
// ponytail: importmap が環境（headless/自動化ブラウザ等）で無視される case があるため、
// bare specifier に頼らず絶対URLで直接 import する（vendor 内ファイルも同様にパッチ済み）。
import * as THREE from "/static/chat/avatar/vendor/three/three.module.js";
import { GLTFLoader } from "/static/chat/avatar/vendor/three/addons/loaders/GLTFLoader.js";
import {
  VRMLoaderPlugin,
  VRMUtils,
} from "/static/chat/avatar/vendor/three-vrm.module.min.js";
import {
  VRMAnimationLoaderPlugin,
  createVRMAnimationClip,
} from "/static/chat/avatar/vendor/three-vrm-animation.module.js";
const FADE = 0.4; // seconds — expression cross-fade
const BLINK_HALF = 0.1; // seconds each way (closed→open)
const TALK_AA_PEAK = 0.8;
const TALK_AA_PERIOD = 0.35; // seconds per mouth open/close cycle
const POSE_LERP = 6; // 1/s — pose transition damping
const REST_ARM_DEG = 70; // 水平からの腕の下げ角（休息姿勢）
const easeInOut = (t) => t * t * (3 - 2 * t);
const D = THREE.MathUtils.degToRad;

// 表情の分類（expressionManager の実在名のみ扱う。実在しない名前は出さない）
const EMOTION_EXPRS = ["neutral", "happy", "angry", "sad", "relaxed"];
const MOUTH_EXPRS = ["aa", "ih", "ou", "ee", "oh"];
const AUTO_EXPRS = [
  "blink",
  "blinkLeft",
  "blinkRight",
  "lookUp",
  "lookDown",
  "lookLeft",
  "lookRight",
];

// ポーズプリセット。腕（upperArm）は「較正した下げ軸まわりの絶対角度（度）」で指定する
// （deg 省略時 = REST_ARM_DEG = 休息姿勢）。deg 以外のオイラー成分と non-arm ボーンは
// 0 基準からのオフセット（度）。未指定ボーンは NEUTRAL へ戻る。
const POSES = {
  neutral: {},
  // 右手を上げて左右に振る（ジェスチャー再生中は lowerArm を揺らす）
  wave: { rightUpperArm: { deg: -55 }, rightLowerArm: { z: -25, y: -15 } },
  // 右手を顎へ（考え中）
  think: {
    rightUpperArm: { deg: 30, x: -20 },
    rightLowerArm: { z: -95 },
    head: { x: -8, y: 10 },
  },
  // お辞儀（腕は休息よりわずかに上げる）
  bow: {
    spine: { x: 28 },
    head: { x: 15 },
    leftUpperArm: { deg: 55 },
    rightUpperArm: { deg: 55 },
  },
};

function checkWebGL() {
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

function showFallback(container) {
  // 既存ヘッダのアバター画像（self portrait）を流用、無ければプレースホルダ
  const headerImg = document.getElementById("chat-persona-avatar");
  const img = document.createElement("img");
  img.alt = "avatar";
  img.className = "chat-avatar-fallback-img";
  if (headerImg && headerImg.src) {
    img.src = headerImg.src;
  } else {
    img.src =
      "data:image/svg+xml;utf8," +
      encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="24" r="14" fill="#8b7bd8"/><ellipse cx="32" cy="54" rx="20" ry="12" fill="#8b7bd8"/></svg>',
      );
  }
  container.appendChild(img);
}

/** No-op handle served when WebGL / model load fails. 契約メソッドを全て持つ。 */
function noopHandle() {
  const nop = () => {};
  return {
    setExpression: nop,
    setTalking: nop,
    setPose: nop,
    playGesture: nop,
    listExpressions: () => ({
      emotions: [],
      mouths: [],
      other: [],
      auto: [],
      bound: [],
    }),
    probe: () => ({
      fallback: true,
      motion: "procedural",
      vrmaBones: 0,
      bones: {},
      armDropDeg: { left: 0, right: 0 },
      framing: { visibleH: 0, visibleW: 0, modelH: 0, modelW: 0, fits: false },
      pose: "neutral",
      idle: { breath: 0, sway: 0 },
      expressions: {},
    }),
    dispose: nop,
    __fallback: true,
  };
}

export function initAvatar(container, modelUrl) {
  if (!container)
    return Promise.reject(new Error("initAvatar: container is null"));
  // 冪等ガード: 2重 init 禁止（init中も含む）
  if (container.__avatarHandle)
    return Promise.resolve(container.__avatarHandle);
  if (container.__avatarIniting) return container.__avatarIniting;

  const inited = _doInit(container, modelUrl);
  container.__avatarIniting = inited;
  inited
    .then((h) => {
      container.__avatarHandle = h;
    })
    .catch(() => {}) // フォールバック済み。外へは漏らさない
    .finally(() => {
      delete container.__avatarIniting;
    });
  return inited;
}

async function _doInit(container, modelUrl) {
  if (!checkWebGL()) {
    console.warn("[avatar] WebGL unavailable — showing fallback image");
    showFallback(container);
    return noopHandle();
  }

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.className = "chat-avatar-canvas";
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  // 背景は透過（チャット画面に馴染ませる）

  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
  // 水平回転(azimuth) + ズーム(自動距離 × ユーザー倍率)
  const orbit = { azimuth: 0 };
  const fit = {
    autoDist: 2.6,
    userZoom: 1.0,
    center: new THREE.Vector3(0, 1.0, 0),
  };

  const lookAtTarget = new THREE.Object3D();
  lookAtTarget.position.copy(camera.position);
  scene.add(lookAtTarget);

  function updateCamera() {
    const r = fit.autoDist * fit.userZoom;
    camera.position.set(
      fit.center.x + r * Math.sin(orbit.azimuth),
      fit.center.y,
      fit.center.z + r * Math.cos(orbit.azimuth),
    );
    camera.lookAt(fit.center);
  }
  updateCamera();

  // モデル bbox 実測 → 縦 fov・横 fov の両方に収まる距離を計算して適用
  const _box = new THREE.Box3();
  const _size = new THREE.Vector3();
  function fitCamera() {
    _box.setFromObject(scene); // vrm.scene は scene に追加済み。ボーン姿勢も反映される
    if (_box.isEmpty()) return;
    _box.getSize(_size);
    const center = _box.getCenter(new THREE.Vector3());
    const fovV = THREE.MathUtils.degToRad(camera.fov);
    const fovH = 2 * Math.atan(Math.tan(fovV / 2) * camera.aspect);
    const margin = 1.08;
    const distV = (_size.y * margin) / (2 * Math.tan(fovV / 2));
    const distW = (_size.x * margin) / (2 * Math.tan(fovH / 2));
    fit.autoDist = Math.max(distV, distW);
    fit.center.copy(center);
    updateCamera();
    lookAtTarget.position.copy(camera.position);
  }

  function resize() {
    const w = container.clientWidth || 640;
    const h = container.clientHeight || 480;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    fitCamera(); // コンテナサイズ変化（--chat-log-h 変更等）に追従して再フィット
  }
  resize();

  // 法線に依存しないフラットなセルシェーディング。指向性ライトを置かず環境光のみにすると
  // MToon の直接光項が消え、法線由来のハイライト／段差グラデーションが出ない（＝白飛びしない）。
  // 陰影はテクスチャに描き込まれた階調がそのまま出る。
  // 強度は実測較正: 従来構成（Directional π×0.8 + Hemisphere π×0.55）の平均輝度 117.8 に対し
  // π では 132.1 と明る過ぎたため、線形な環境光項を ×0.9 して同輝度（≒119）に合わせる。
  scene.add(new THREE.AmbientLight(0xffffff, Math.PI * 0.9));

  // --- ポインタドラッグ: 水平回転 / ホイール: ズーム（自動距離 × 倍率） ---
  let dragging = false,
    lastX = 0;
  const el = renderer.domElement;
  el.style.touchAction = "none";
  const onPointerDown = (e) => {
    dragging = true;
    lastX = e.clientX;
    el.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e) => {
    if (!dragging) return;
    orbit.azimuth += (e.clientX - lastX) * 0.005;
    lastX = e.clientX;
    updateCamera();
    lookAtTarget.position.copy(camera.position);
  };
  const onPointerUp = () => {
    dragging = false;
  };
  const onWheel = (e) => {
    e.preventDefault();
    // ユーザー倍率のみを変更する。自動再フィット（resize 等）には上書きされない
    fit.userZoom = Math.min(
      2.5,
      Math.max(0.4, fit.userZoom * (1 + e.deltaY * 0.001)),
    );
    updateCamera();
    lookAtTarget.position.copy(camera.position);
  };
  el.addEventListener("pointerdown", onPointerDown);
  el.addEventListener("pointermove", onPointerMove);
  el.addEventListener("pointerup", onPointerUp);
  el.addEventListener("pointercancel", onPointerUp);
  el.addEventListener("wheel", onWheel, { passive: false });
  const ro =
    typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
  if (ro) ro.observe(container);

  let vrm;
  let gltfParser = null;
  try {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
    const gltf = await new Promise((resolve, reject) => {
      loader.load(modelUrl, resolve, undefined, reject);
    });
    vrm = gltf.userData.vrm;
    // 材質テクスチャの引き直し（bindBaseColorTextures）で使う
    gltfParser = gltf.parser ?? null;
    // VRM 0.x は-Z面向き → 180°回してカメラ(+Z)を向かせる（VRM1はno-op）
    VRMUtils.rotateVRM0(vrm);
    // ponytail: スプリングボーン（髪/リボン等）がヘッドレス環境・負荷時 dt スパイクで
    // 爆発して崩壊描画になる case がある。物理無効化フラグは data-attr で上書き可。
    if (container.dataset.avatarSpringbone === "off") {
      vrm.springBoneManager = null;
    }
    scene.add(vrm.scene);
    vrm.lookAt.target = lookAtTarget;
    vrm.springBoneManager?.reset();
  } catch (e) {
    console.warn("[avatar] VRM load failed:", e?.message ?? e);
    try {
      ro?.disconnect();
    } catch {
      /* noop */
    }
    renderer.dispose();
    el.remove();
    showFallback(container);
    return noopHandle();
  }

  const humanoid = vrm.humanoid;
  const nBone = (name) => humanoid.getNormalizedBoneNode(name);
  const hasChest = !!nBone("chest");

  // --- VRMA 待機モーション: .vrma ファイルを別 GLTFLoader で読み、成功したら 'vrma'。失敗/無効なら 'procedural' ---
  // 強制フォールバック手段: container.dataset.avatarVrma === 'off' / URL 上書き: dataset.avatarVrmaUrl
  let motion = "procedural",
    vrmaMixer = null,
    vrmaAction = null,
    vrmaBones = new Set();
  if (container.dataset.avatarVrma !== "off") {
    try {
      const vrmaUrl =
        container.dataset.avatarVrmaUrl ||
        "/static/chat/avatar/animations/idle_loop.vrma";
      const animLoader = new GLTFLoader();
      animLoader.register((parser) => new VRMAnimationLoaderPlugin(parser));
      const animGltf = await animLoader.loadAsync(vrmaUrl);
      const vrma =
        animGltf.userData.vrmAnimation ?? animGltf.userData.vrmAnimations?.[0];
      if (vrma) {
        const clip = createVRMAnimationClip(vrma, vrm);
        // クリップが実際にトラックを持つボーンの集合（トラック名は <ノード名>.quaternion 等の規約）
        vrmaBones = new Set();
        // トラック名は正規化ノード名（例 "Normalized_head.quaternion"）。mixer の書込み先も正規化ノードなので、正規化ノードで照合する
        const trackNodes = new Set(
          clip.tracks.map((t) => t.name.slice(0, t.name.lastIndexOf("."))),
        );
        for (const name of Object.keys(vrm.humanoid.humanBones)) {
          const n = nBone(name);
          if (n && trackNodes.has(n.name)) vrmaBones.add(n);
        }
        vrmaMixer = new THREE.AnimationMixer(vrm.scene);
        vrmaAction = vrmaMixer.clipAction(clip);
        vrmaAction.play();
        motion = "vrma";
      }
    } catch (e) {
      console.warn(
        "[avatar] VRMA load failed, falling back to procedural idle:",
        e?.message ?? e,
      );
      vrmaMixer = null;
      vrmaAction = null;
    }
  }

  // --- 腕の較正: どの(軸, 符号)で回すと手首のワールド Y が最も下がるかを実測 ---
  // 正規化ボーンの局所軸はモデル依存のため推測しない。較正は元の回転に復元してから返す。
  function calibrateArm(side) {
    const upper = nBone(side + "UpperArm");
    const hand = nBone(side + "Hand");
    if (!upper || !hand) return null;
    const v = new THREE.Vector3();
    const rot0 = upper.rotation.clone();
    upper.updateWorldMatrix(true, true);
    const baseY = hand.getWorldPosition(v).y;
    let best = null;
    for (const axis of ["x", "y", "z"]) {
      for (const sign of [1, -1]) {
        upper.rotation.set(0, 0, 0);
        upper.rotation[axis] = sign * 0.3;
        upper.updateWorldMatrix(true, true);
        const y = hand.getWorldPosition(v).y;
        if (!best || y < best.y) best = { axis, sign, y };
      }
    }
    upper.rotation.copy(rot0);
    upper.updateWorldMatrix(true, true);
    // どの候補も手を下げられない（すでに下ろしている等）→ 較正失敗として扱う
    if (!best || best.y >= baseY - 0.005) return null;
    return best;
  }
  const armCal = { left: calibrateArm("left"), right: calibrateArm("right") };

  // --- 腕の下げ角（水平からの実測・度）。probe() 用に毎回実測する ---
  function measureArmDropDeg(side) {
    const upper = nBone(side + "UpperArm");
    const hand = nBone(side + "Hand");
    if (!upper || !hand) return 0;
    const shoulder = nBone(side + "Shoulder") || upper.parent;
    const hp = hand.getWorldPosition(new THREE.Vector3());
    const sp = shoulder.getWorldPosition(new THREE.Vector3());
    const dx = hp.x - sp.x,
      dy = hp.y - sp.y,
      dz = hp.z - sp.z;
    return THREE.MathUtils.radToDeg(Math.atan2(-dy, Math.hypot(dx, dz)));
  }


  // --- MToon リム（控えめなラベンダー系。アウトラインは触らない） ---
  const rimColor = new THREE.Color(0.55, 0.48, 0.7);
  // three-vrm v3 の正準名は *Factor。旧名エイリアスのみの版もあり得るので両方に入れる
  const setFactor = (m, name, value) => {
    if (name in m) m[name] = value;
    const legacy = name.replace(/Factor$/, "");
    if (legacy !== name && legacy in m) m[legacy] = value;
  };
  vrm.scene.traverse((o) => {
    const mats = Array.isArray(o.material)
      ? o.material
      : o.material
        ? [o.material]
        : [];
    for (const m of mats) {
      if (!m.isMToonMaterial || m.isOutline) continue;
      m.parametricRimColorFactor?.copy(rimColor);
      setFactor(m, "parametricRimFresnelPowerFactor", 2.5);
      setFactor(m, "rimLightingMixFactor", 0.3);
    }
  });

  // --- アウトライン: VRM の outlineWidthFactor は既定 0.00065m。この描画倍率では 1px ≒ 0.0074m
  // （身長 1.6m / 表示 215px）なので実質不可視（約 0.09px）。可視幅まで引き上げて線を出す。
  // 色は VRM 側の指定（outlineColorFactor）をそのまま使う。
  const OUTLINE_WIDTH = 0.012; // 実測: 層内 3.8% の画素が変わり、2px 弱の線が出る
  vrm.scene.traverse((o) => {
    const mats = Array.isArray(o.material)
      ? o.material
      : o.material
        ? [o.material]
        : [];
    for (const m of mats) {
      if (!m.isMToonMaterial) continue;
      if ((m.outlineWidthFactor ?? 0) < OUTLINE_WIDTH) {
        setFactor(m, "outlineWidthFactor", OUTLINE_WIDTH);
      }
    }
  });

  // --- まばたき: time-based ランダムスケジューラ ---
  const blink = { next: 2 + Math.random() * 6, w: 0, phase: null };
  function updateBlink() {
    const t = performance.now() / 1000;
    if (blink.phase === null) {
      if (t >= blink.next) blink.phase = { start: t };
    } else {
      const p = (t - blink.phase.start) / BLINK_HALF;
      if (p >= 2) {
        blink.w = 0;
        blink.phase = null;
        blink.next = t + 2 + Math.random() * 6;
      } else {
        blink.w = p <= 1 ? p : 2 - p;
      }
    }
    vrm.expressionManager.setValue("blink", blink.w);
  }

  // --- ポーズ: ボーン回転の目標へ減速補間 ---
  // 腕は較正結果（下げ軸まわりの絶対角）を含めた基準姿勢。プリセットは上書き。
  const pose = {
    name: "neutral",
    target: {}, // bone -> {x,y,z} rad（休息姿勢込み）
    cur: {}, // bone -> {x,y,z} rad（減速補間中の基準値）
  };
  function poseTargets(name) {
    const t = {};
    const preset = POSES[name] || {};
    // 腕: 較正した下げ軸まわりの絶対角度で組む（deg 未指定 = 休息 70°）
    for (const side of ["left", "right"]) {
      const cal = armCal[side];
      if (!cal) continue;
      const bone = side + "UpperArm";
      const p = preset[bone] || {};
      const deg = typeof p.deg === "number" ? p.deg : REST_ARM_DEG;
      const r = { x: 0, y: 0, z: 0 };
      for (const k of Object.keys(p)) {
        if (k !== "deg") r[k] = D(p[k]);
      }
      r[cal.axis] = D(deg * cal.sign); // deg 指定を最優先（軸成分の衝突を上書き）
      t[bone] = r;
    }
    // 腕以外（lowerArm / spine / head 等）: 0 基準のオイラーオフセット
    for (const [b, r] of Object.entries(preset)) {
      if (t[b]) continue;
      t[b] = {
        x: 0,
        y: 0,
        z: 0,
        ...Object.fromEntries(
          Object.entries(r)
            .filter(([k]) => k !== "deg")
            .map(([k, v]) => [k, D(v)]),
        ),
      };
    }
    return t;
  }
  function setPose(name) {
    if (!POSES[name]) name = "neutral";
    pose.name = name;
    pose.target = poseTargets(name);
    for (const b of Object.keys(pose.target)) {
      if (!pose.cur[b]) pose.cur[b] = { x: 0, y: 0, z: 0 };
    }
  }
  setPose("neutral");

  // ジェスチャー: 指定時間だけ再生するオフセットモーション（純関数・加算代入なし）
  const gestures = [];
  function playGesture(name) {
    if (name === "nod") gestures.push({ kind: "nod", t: 0, dur: 1.2 });
    else if (name === "wave") gestures.push({ kind: "wave", t: 0, dur: 1.8 });
    else if (name === "bounce")
      gestures.push({ kind: "bounce", t: 0, dur: 0.9 });
    else if (name === "shake") gestures.push({ kind: "shake", t: 0, dur: 1.0 });
  }
  function offAdd(off, bone, x, y, z) {
    const o = off[bone] || (off[bone] = { x: 0, y: 0, z: 0 });
    o.x = o.x + x;
    o.y = o.y + y;
    o.z = o.z + z;
  }
  function gestureOffset(g, p, off) {
    if (g.kind === "nod")
      offAdd(off, "head", D(10 * Math.sin(p * Math.PI * 2) * (1 - p)), 0, 0);
    else if (g.kind === "wave")
      offAdd(
        off,
        "rightLowerArm",
        0,
        D(30 * Math.sin(p * Math.PI * 5) * Math.min(p * 3, 1)),
        0,
      );
    else if (g.kind === "bounce")
      offAdd(off, "spine", D(-4 * Math.sin(p * Math.PI * 2) * (1 - p)), 0, 0);
    else if (g.kind === "shake")
      offAdd(off, "head", 0, D(14 * Math.sin(p * Math.PI * 3) * (1 - p)), 0);
  }

  // idle 振幅・腕角度の実測用サンプル（直近 ~4.5 秒の ring buffer。呼吸周期 4 秒を
  // 丸ごと含む窓にしないと、窓が位相の山/谷に当たった時だけ過小測定される）
  // 腕角は VRMA 中も手が揺れるため、瞬時値ではなく窓平均を probe() に返す
  const idleSamples = [];
  function recordIdle(t, breath, sway, dropL, dropR) {
    idleSamples.push({ t, breath, sway, dropL, dropR });
    while (idleSamples.length && idleSamples[0].t < t - 4.6)
      idleSamples.shift();
  }
  function idleAmps() {
    const now = idleSamples.length ? idleSamples[idleSamples.length - 1].t : 0;
    const s = idleSamples.filter((p) => now - p.t <= 4.2);
    if (s.length < 2) return { breath: 0, sway: 0, dropL: 0, dropR: 0 };
    const amp = (f) => (Math.max(...s.map(f)) - Math.min(...s.map(f))) / 2;
    const avg = (f) => s.reduce((a, p) => a + f(p), 0) / s.length;
    return {
      breath: amp((p) => p.breath),
      sway: amp((p) => p.sway),
      dropL: avg((p) => p.dropL),
      dropR: avg((p) => p.dropR),
    };
  }

  // hips: 休息位置を保存しておき、体重移動は position の絶対再構成で行う
  const hipsNode = nBone("hips");
  const hipsRest = hipsNode ? hipsNode.position.clone() : null;

  // 毎フレーム更新（固定順）:
  //   1. mixer.update(dt) — VRMA が骨盤・背骨・腕を動かす（neumoral pose 時は一時停止）
  //   2. updatePose(dt)   — 呼吸/体重移動/頭の微動を追加層として上書き合成（VRMA 中は振幅 ×0.5）
  //   3. vrm.update(dt)   — スキン＋揺れ物＋表情
  function updatePose(dt, elapsed) {
    if (!pose.target) return;
    const k = Math.min(1, POSE_LERP * dt);
    const useVrma = motion === "vrma" && pose.name === "neutral";
    // VRMA 再生中は休息姿勢の固定角を適用しない（VRMA が腕の下げを担う）
    if (vrmaAction) vrmaAction.paused = !useVrma;
    const A = useVrma ? 0.5 : 1; // プロシージャル層の振幅スケール
    const TAU = Math.PI * 2;
    // 呼吸: 周期 4 秒 + 短周期の重ね合わせ（目視で分かる振幅）
    const breath =
      Math.sin((TAU * elapsed) / 4) +
      0.35 * Math.sin((TAU * elapsed) / 2.6 + 1.1);
    // 体重移動: 腰の水平移動（互いに割り切れない 2 周期）
    const swayX = 0.02 * Math.sin((TAU * elapsed) / 6.4);
    const swayZ = 0.012 * Math.sin((TAU * elapsed) / 9.7 + 0.7);
    const swayPhase = (TAU * elapsed) / 6.4;

    const off = {
      spine: {
        x:
          D(3.0 * breath * A) +
          (fade.name === "angry" ? D(3) : 0) +
          (fade.name === "happy"
            ? D(-3 * Math.abs(Math.sin(elapsed * 2.2)))
            : 0),
        y: 0,
        z: D(2.0 * Math.sin(swayPhase + 0.5) * A), // 体重移動への対傾斜
      },
    };
    if (hasChest) off.chest = { x: D(1.5 * breath * A), y: 0, z: 0 };
    // 頭の微動: 互いに割り切れない周期の重ね合わせ（ループ感を消す）
    off.head = {
      x:
        D(
          1.6 * Math.sin((TAU * elapsed) / 5.1) * A +
            0.6 * Math.sin((TAU * elapsed) / 7.7 + 2.0) * A,
        ) +
        (fade.name === "sad" ? D(6) : 0) +
        (talking ? D(2.5 * Math.sin((TAU * elapsed) / 0.9)) : 0),
      y: D(2.4 * Math.sin((TAU * elapsed) / 7.3 + 1.2) * A),
      z: D(1.2 * Math.sin((TAU * elapsed) / 11.3 + 0.4) * A),
    };
    // 腕の追従揺れ（呼吸・体重移動に同期、左右逆位相）
    for (const side of ["left", "right"]) {
      const cal = armCal[side];
      if (!cal) continue;
      const ph = side === "left" ? 0 : Math.PI;
      offAdd(off, side + "UpperArm", 0, 0, 0);
      off[side + "UpperArm"][cal.axis] = D(
        (1.8 * Math.sin((TAU * elapsed) / 4 + ph) +
          1.2 * Math.sin(swayPhase + ph)) *
          A,
      );
    }
    // ジェスチャー
    for (const g of gestures) {
      g.t = g.t + dt;
      const p = g.t / g.dur;
      if (p < 1) gestureOffset(g, p, off);
    }
    for (let i = gestures.length - 1; i >= 0; i--) {
      if (gestures[i].t >= gestures[i].dur) gestures.splice(i, 1);
    }

    if (useVrma) {
      // 追加層: VRMA の揺れを小さなオフセットとして合成（×0.5 振幅）。
      // トラックを持つ骨は mixer が毎フレーム quaternion を上書きするため乗算合成でよい。
      // トラックを持たない骨は mixer が書き戻さないため乗算が毎フレーム累積する → プロシージャル経路と同じ絶対再構成で上書きする。
      for (const [b, o] of Object.entries(off)) {
        const node = nBone(b);
        if (!node) continue;
        if (vrmaBones.has(node)) {
          _tmpE.set(o.x, o.y, o.z);
          _tmpQ.setFromEuler(_tmpE);
          node.quaternion.multiply(_tmpQ);
        } else {
          const tgt = pose.target[b] || { x: 0, y: 0, z: 0 };
          const c = pose.cur[b] || (pose.cur[b] = { x: 0, y: 0, z: 0 });
          c.x = c.x + (tgt.x - c.x) * k;
          c.y = c.y + (tgt.y - c.y) * k;
          c.z = c.z + (tgt.z - c.z) * k;
          node.rotation.set(c.x + o.x, c.y + o.y, c.z + o.z);
        }
      }
      recordIdle(
        elapsed,
        D(3.0 * breath * A),
        swayX,
        measureArmDropDeg("left"),
        measureArmDropDeg("right"),
      );
      return;
    }

    // 書き込み: 基準姿勢のボーン ∪ オフセット対象ボーン（絶対再構成）
    const bones = new Set([...Object.keys(pose.cur), ...Object.keys(off)]);
    for (const b of bones) {
      const node = nBone(b);
      if (!node) continue;
      const tgt = pose.target[b] || { x: 0, y: 0, z: 0 };
      const c = pose.cur[b] || (pose.cur[b] = { x: 0, y: 0, z: 0 });
      c.x = c.x + (tgt.x - c.x) * k;
      c.y = c.y + (tgt.y - c.y) * k;
      c.z = c.z + (tgt.z - c.z) * k;
      const o = off[b] || { x: 0, y: 0, z: 0 };
      node.rotation.set(c.x + o.x, c.y + o.y, c.z + o.z);
    }
    // hips: 位置は絶対再構成（休息位置 + 揺れ）
    if (hipsNode && hipsRest) {
      hipsNode.position.set(
        hipsRest.x + swayX,
        hipsRest.y + 0.006 * breath,
        hipsRest.z + swayZ,
      );
    }
    recordIdle(
      elapsed,
      D(3.0 * breath * A),
      swayX,
      measureArmDropDeg("left"),
      measureArmDropDeg("right"),
    );
  }

  // --- 表情: 実在名のみ扱う（0.4s fade） ---
  const em = vrm.expressionManager;
  const exprNames = em ? em.expressions.map((e) => e.expressionName) : [];
  const fade = { from: 0, weight: 0, name: "neutral", t: FADE, cur: 0 };
  function setExpression(name, weight) {
    // 任意の名前を受け付ける。VRM に存在しない名前は無視（現在値を保持）
    if (!em || !em.getExpression(name)) return;
    fade.from = fade.cur;
    fade.name = name;
    fade.weight =
      typeof weight === "number" ? Math.min(1, Math.max(0, weight)) : 0.7;
    fade.t = 0;
  }
  function updateExpression(dt) {
    if (fade.t < FADE) {
      fade.t = Math.min(fade.t + dt, FADE);
      const k = Math.min(fade.t / FADE, 1);
      fade.cur = fade.from + (fade.weight - fade.from) * easeInOut(k);
    } else {
      fade.cur = fade.weight;
    }
    // 実在する全表情を毎フレーム絶対代入（前回選択の取りこぼしも消える）。
    // auto（blink*/look*）は blink システムが管理するため触らない。
    for (const n of exprNames) {
      if (AUTO_EXPRS.includes(n)) continue;
      em.setValue(n, n === fade.name ? fade.cur : 0);
    }
  }

  // --- 発話 (aa): setTalking(true) で 0→peak→0 往復ループ ---
  let talking = false,
    talkT = 0;
  function setTalking(on) {
    talking = !!on;
    if (!talking) {
      talkT = 0;
      em?.setValue("aa", 0);
    }
  }
  function updateTalking(dt) {
    if (!talking) return;
    talkT = (talkT + dt) % TALK_AA_PERIOD;
    const phase = talkT / TALK_AA_PERIOD; // 0..1
    const tri = phase < 0.5 ? phase * 2 : 2 - phase * 2; // 0→1→0
    em?.setValue("aa", tri * TALK_AA_PEAK);
  }

  // --- メインループ ---
  let disposed = false;
  const clock = new THREE.Clock();
  const _tmpE = new THREE.Euler();
  const _tmpQ = new THREE.Quaternion();
  function loop() {
    if (disposed) return;
    requestAnimationFrame(loop);
    const dt = clock.getDelta();
    updateBlink();
    updateExpression(dt);
    updateTalking(dt);
    if (vrmaMixer) vrmaMixer.update(dt); // 1. VRMA 先行（プロシージャル層の前にボーンを動かす）
    updatePose(dt, clock.elapsedTime); // 2. 呼吸/体重移動/頭の微動を上書き合成
    vrm.update(dt); // 3. スキン＋揺れ物
    renderer.render(scene, camera);
  }

  // 休息姿勢を適用してからカメラをフィット（bbox が休息姿勢を反映するように）
  for (const [b, r] of Object.entries(pose.target)) {
    const node = nBone(b);
    if (node) node.rotation.set(r.x, r.y, r.z);
  }
  vrm.update(0);
  fitCamera();
  loop();

  function listExpressions() {
    const names = em ? em.expressions.map((e) => e.expressionName) : [];
    const bucket = (list) => names.filter((n) => list.includes(n));
    const known = new Set([...EMOTION_EXPRS, ...MOUTH_EXPRS, ...AUTO_EXPRS]);
    // VRM 0.x はプリセット名を空のまま事前登録するため、名前はあるが効果が無い式がある。
    // 実バインド（モーフ/材質値）を持つ式だけを bound として公開する。
    const bound = (em?.expressions ?? [])
      .filter((e) => (e.binds?.length ?? 0) > 0)
      .map((e) => e.expressionName);
    return {
      emotions: bucket(EMOTION_EXPRS),
      mouths: bucket(MOUTH_EXPRS),
      other: names.filter((n) => !known.has(n)),
      auto: bucket(AUTO_EXPRS),
      bound,
    };
  }

  function probe() {
    const box = new THREE.Box3().setFromObject(vrm.scene);
    const size = box.isEmpty()
      ? new THREE.Vector3()
      : box.getSize(new THREE.Vector3());
    const dist = fit.autoDist * fit.userZoom;
    const fovV = THREE.MathUtils.degToRad(camera.fov);
    const visibleH = 2 * dist * Math.tan(fovV / 2);
    const visibleW = visibleH * camera.aspect;
    const expressions = {};
    if (em) for (const n of exprNames) expressions[n] = em.getValue(n) ?? 0;
    const idle = idleAmps();
    return {
      fallback: false,
      motion,
      vrmaBones: vrmaBones.size,
      bones: {
        leftUpperArm: !!nBone("leftUpperArm"),
        rightUpperArm: !!nBone("rightUpperArm"),
        leftHand: !!nBone("leftHand"),
      },
      armDropDeg: {
        left: idle.dropL || measureArmDropDeg("left"),
        right: idle.dropR || measureArmDropDeg("right"),
      },
      framing: {
        visibleH,
        visibleW,
        modelH: size.y,
        modelW: size.x,
        fits: size.y <= visibleH * 1.01 && size.x <= visibleW * 1.01,
        container: { w: container.clientWidth, h: container.clientHeight },
        autoDist: fit.autoDist,
        userZoom: fit.userZoom,
      },
      pose: pose.name,
      idle,
      expressions,
    };
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    try {
      ro?.disconnect();
    } catch {
      /* noop */
    }
    el.removeEventListener("pointerdown", onPointerDown);
    el.removeEventListener("pointermove", onPointerMove);
    el.removeEventListener("pointerup", onPointerUp);
    el.removeEventListener("pointercancel", onPointerUp);
    el.removeEventListener("wheel", onWheel);
    try {
      VRMUtils.deepDispose(vrm.scene);
    } catch {
      /* 古い three-vrm では deepDispose 無し */
    }
    renderer.dispose();
    el.remove();
    container.innerHTML = "";
    delete container.__avatarHandle;
  }

  return {
    setExpression,
    setTalking,
    setPose,
    playGesture,
    listExpressions,
    probe,
    dispose,
    __vrm: vrm,
    __parser: gltfParser,
  };
}
