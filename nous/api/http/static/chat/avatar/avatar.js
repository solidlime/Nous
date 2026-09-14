/* =================================================================
   VRM avatar module for character chat mode.
   Adapted from prototype/vrm-avatar/main.js (drawing core only).
   Exports initAvatar(container, modelUrl) -> Promise<handle>.

   handle = { setExpression(name, weight), setTalking(on), dispose() }
   WebGL unavailable / load failure → static fallback in container,
   promise still resolves (no-ops) so callers never need error paths.
   ================================================================= */
// ponytail: importmap が環境（headless/自動化ブラウザ等）で無視される case があるため、
// bare specifier に頼らず絶対URLで直接 import する（vendor 内ファイルも同様にパッチ済み）。
import * as THREE from '/static/chat/avatar/vendor/three/three.module.js';
import { GLTFLoader } from '/static/chat/avatar/vendor/three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '/static/chat/avatar/vendor/three-vrm.module.min.js';

const EMOTIONS = ['happy', 'surprised', 'sad', 'angry', 'relaxed', 'neutral'];
const FADE = 0.4;      // seconds — expression cross-fade
const BLINK_HALF = 0.1; // seconds each way (closed→open)
const TALK_AA_PEAK = 0.8;
const TALK_AA_PERIOD = 0.35; // seconds per mouth open/close cycle
const POSE_LERP = 6;   // 1/s — pose transition damping
const easeInOut = (t) => t * t * (3 - 2 * t);

// ポーズプリセット: 正規化ボーンの目標オイラー角（度）。未指定ボーンは NEUTRAL へ戻る。
const D = THREE.MathUtils.degToRad;
const A_POSE = { leftUpperArm: { z: -70 }, rightUpperArm: { z: 70 } };
const POSES = {
  neutral: {},
  // 右手を上げて左右に振る（ジェスチャー再生中は lowerArm を揺らす）
  wave: { rightUpperArm: { z: -55 }, rightLowerArm: { z: -25, y: -15 } },
  // 右手を顎へ（考え中）
  think: { rightUpperArm: { x: -35, z: 45 }, rightLowerArm: { z: -95 }, head: { x: -8, y: 10 } },
  // お辞儀
  bow: { spine: { x: 28 }, head: { x: 15 }, leftUpperArm: { z: -55 }, rightUpperArm: { z: 55 } },
};

function checkWebGL() {
  try {
    const canvas = document.createElement('canvas');
    return !!(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

function showFallback(container) {
  // 既存ヘッダのアバター画像（self portrait）を流用、無ければプレースホルダ
  const headerImg = document.getElementById('chat-persona-avatar');
  const img = document.createElement('img');
  img.alt = 'avatar';
  img.className = 'chat-avatar-fallback-img';
  if (headerImg && headerImg.src) {
    img.src = headerImg.src;
  } else {
    img.src =
      'data:image/svg+xml;utf8,' +
      encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="24" r="14" fill="#8b7bd8"/><ellipse cx="32" cy="54" rx="20" ry="12" fill="#8b7bd8"/></svg>'
      );
  }
  container.appendChild(img);
}

/** No-op handle served when WebGL / model load fails. */
function noopHandle() {
  const nop = () => {};
  return { setExpression: nop, setTalking: nop, setPose: nop, playGesture: nop, dispose: nop, __fallback: true };
}

export function initAvatar(container, modelUrl) {
  if (!container) return Promise.reject(new Error('initAvatar: container is null'));
  // 冪等ガード: 2重 init 禁止（init中も含む）
  if (container.__avatarHandle) return Promise.resolve(container.__avatarHandle);
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
    console.warn('[avatar] WebGL unavailable — showing fallback image');
    showFallback(container);
    return noopHandle();
  }

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.className = 'chat-avatar-canvas';
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  // 背景は透過（チャット画面に馴染ませる）

  const TARGET = new THREE.Vector3(0, 1.2, 0);
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
  // 水平回転(azimuth) + ズーム(radius, clamp 1.2〜4m)
  const orbit = { azimuth: 0, radius: 2.6 };
  const RADIUS_MIN = 1.2, RADIUS_MAX = 4.0;

  function updateCamera() {
    const y = 1.4;
    camera.position.set(
      TARGET.x + orbit.radius * Math.sin(orbit.azimuth),
      y,
      TARGET.z + orbit.radius * Math.cos(orbit.azimuth)
    );
    camera.lookAt(TARGET);
  }
  updateCamera();

  function resize() {
    const w = container.clientWidth || 640;
    const h = container.clientHeight || 480;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }
  resize();

  const dirLight = new THREE.DirectionalLight(0xffffff, Math.PI * 0.8);
  dirLight.position.set(1.5, 3, 2);
  scene.add(dirLight);
  scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x40382f, Math.PI * 0.55));

  const lookAtTarget = new THREE.Object3D();
  lookAtTarget.position.copy(camera.position);
  scene.add(lookAtTarget);

  // --- ポインタドラッグ: 水平回転 / ホイール: zoom ---
  let dragging = false, lastX = 0;
  const el = renderer.domElement;
  el.style.touchAction = 'none';
  const onPointerDown = (e) => { dragging = true; lastX = e.clientX; el.setPointerCapture?.(e.pointerId); };
  const onPointerMove = (e) => {
    if (!dragging) return;
    orbit.azimuth += (e.clientX - lastX) * 0.005;
    lastX = e.clientX;
    updateCamera();
    lookAtTarget.position.copy(camera.position);
  };
  const onPointerUp = () => { dragging = false; };
  const onWheel = (e) => {
    e.preventDefault();
    orbit.radius = Math.min(RADIUS_MAX, Math.max(RADIUS_MIN, orbit.radius + e.deltaY * 0.002));
    updateCamera();
    lookAtTarget.position.copy(camera.position);
  };
  el.addEventListener('pointerdown', onPointerDown);
  el.addEventListener('pointermove', onPointerMove);
  el.addEventListener('pointerup', onPointerUp);
  el.addEventListener('pointercancel', onPointerUp);
  el.addEventListener('wheel', onWheel, { passive: false });
  const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize);
  if (ro) ro.observe(container);

  // --- VRM ロード ---
  let vrm;
  try {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await new Promise((resolve, reject) => {
      loader.load(modelUrl, resolve, undefined, reject);
    });
    vrm = gltf.userData.vrm;
    // VRM 0.x は-Z面向き → 180°回してカメラ(+Z)を向かせる（VRM1はno-op）
    VRMUtils.rotateVRM0(vrm);
    // ponytail: スプリングボーン（髪/リボン等）がヘッドレス環境・負荷時 dt スパイクで
    // 爆発して崩壊描画になる case がある。物理無効化フラグは data-attr で上書き可。
    if (container.dataset.avatarSpringbone === 'off') {
      vrm.springBoneManager = null;
    }
    scene.add(vrm.scene);
    vrm.lookAt.target = lookAtTarget;
    vrm.springBoneManager?.reset();
  } catch (e) {
    console.warn('[avatar] VRM load failed:', e?.message ?? e);
    try { ro?.disconnect(); } catch { /* noop */ }
    renderer.dispose();
    el.remove();
    showFallback(container);
    return noopHandle();
  }

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
    vrm.expressionManager.setValue('blink', blink.w);
  }

  // --- ポーズ: ボーン回転の目標へ減速補間 ---
  // Aポーズ（腕下ろし）を基準に含め、プリセットを上乗せ。
  const pose = {
    name: 'neutral',
    target: {}, // bone -> {x,y,z} rad（Aポーズ込み）
    cur: {},    // bone -> {x,y,z} rad（減速補間中の基準値）
  };
  function poseTargets(name) {
    const t = {};
    for (const [b, r] of Object.entries(A_POSE)) t[b] = { x: 0, y: 0, ...r };
    for (const [b, r] of Object.entries(POSES[name] || {})) {
      t[b] = { ...(t[b] || { x: 0, y: 0, z: 0 }), ...r };
    }
    return t;
  }
  function setPose(name) {
    if (!POSES[name]) name = 'neutral';
    pose.name = name;
    pose.target = poseTargets(name);
    for (const b of Object.keys(pose.target)) {
      if (!pose.cur[b]) pose.cur[b] = { x: 0, y: 0, z: 0 };
    }
  }
  setPose('neutral');

  // ジェスチャー: 指定時間だけ再生するオフセットモーション（純関数・加算代入なし）
  const gestures = [];
  function playGesture(name) {
    if (name === 'nod') gestures.push({ kind: 'nod', t: 0, dur: 1.2 });
    else if (name === 'wave') gestures.push({ kind: 'wave', t: 0, dur: 1.8 });
    else if (name === 'bounce') gestures.push({ kind: 'bounce', t: 0, dur: 0.9 });
    else if (name === 'shake') gestures.push({ kind: 'shake', t: 0, dur: 1.0 });
  }
  function gestureOffset(g, p, off) {
    if (g.kind === 'nod') off.head.x += D(10 * Math.sin(p * Math.PI * 2) * (1 - p));
    else if (g.kind === 'wave') off.rightLowerArm.y += D(30 * Math.sin(p * Math.PI * 5) * Math.min(p * 3, 1));
    else if (g.kind === 'bounce') off.spine.x += D(-4 * Math.sin(p * Math.PI * 2) * (1 - p));
    else if (g.kind === 'shake') off.head.y += D(14 * Math.sin(p * Math.PI * 3) * (1 - p));
  }

  // 毎フレーム「基準姿勢(lerp) + 時間依存オフセット」を再構成して代入する。
  // 加算代入（+=）は使わない —— 復元力がなく無限累積するため（レビュー指摘対応）。
  function updatePose(dt, elapsed) {
    if (!pose.target) return;
    const k = Math.min(1, POSE_LERP * dt);
    const off = {
      spine: { x: 0, y: 0, z: 0 },
      head: { x: 0, y: 0, z: 0 },
    };
    // 呼吸/idle 揺れ
    off.spine.z += D(1.5 * Math.sin((elapsed * Math.PI * 2) / 4) * 0.1);
    off.head.x += D(0.8 * Math.sin(elapsed * 0.6));
    off.head.y += D(1.2 * Math.sin(elapsed * 0.4 + 1.7));
    // 感情の身体挙動（定数・振動ともにオフセットとして毎フレーム再計算）
    if (fade.name === 'angry') off.spine.x += D(3); // 前傾
    if (fade.name === 'happy') off.spine.x += D(-3 * Math.abs(Math.sin(elapsed * 2.2))); // 弾む
    if (fade.name === 'sad') off.head.x += D(6); // うつむき
    // 会話中の小さなうなずき
    if (talking) off.head.x += D(2.5 * Math.sin((elapsed * Math.PI * 2) / 0.9));
    // ジェスチャー
    for (const g of gestures) {
      g.t += dt;
      const p = g.t / g.dur;
      if (p < 1) gestureOffset(g, p, off);
    }
    for (let i = gestures.length - 1; i >= 0; i--) {
      if (gestures[i].t >= gestures[i].dur) gestures.splice(i, 1);
    }
    // 書き込み: 基準姿勢のボーン ∪ オフセット対象ボーン
    const bones = new Set([...Object.keys(pose.cur), ...Object.keys(off)]);
    for (const b of bones) {
      const node = vrm.humanoid.getNormalizedBoneNode(b);
      if (!node) continue;
      const tgt = pose.target[b] || { x: 0, y: 0, z: 0 };
      const c = pose.cur[b] || (pose.cur[b] = { x: 0, y: 0, z: 0 });
      c.x += (tgt.x - c.x) * k;
      c.y += (tgt.y - c.y) * k;
      c.z += (tgt.z - c.z) * k;
      const o = off[b] || { x: 0, y: 0, z: 0 };
      node.rotation.set(c.x + o.x, c.y + o.y, c.z + o.z);
    }
  }

  // --- 表情: setExpression 指定のみ（0.4s fade） ---
  const fade = { from: 0, weight: 0, name: 'neutral', t: FADE };
  function setExpression(name, weight) {
    if (!EMOTIONS.includes(name)) name = 'neutral';
    fade.from = fade.weight;
    fade.name = name;
    fade.weight = typeof weight === 'number' ? weight : 0.7;
    fade.t = 0;
  }
  function updateExpression(dt) {
    if (fade.t < FADE) {
      fade.t += dt;
      const k = Math.min(fade.t / FADE, 1);
      fade.cur = fade.from + (fade.weight - fade.from) * easeInOut(k);
    } else {
      fade.cur = fade.weight;
    }
    for (const e of EMOTIONS) {
      vrm.expressionManager.setValue(e, e === fade.name ? fade.cur : 0);
    }
  }

  // --- 発話 (aa): setTalking(true) で 0→peak→0 往復ループ ---
  let talking = false, talkT = 0;
  function setTalking(on) {
    talking = !!on;
    if (!talking) {
      talkT = 0;
      vrm.expressionManager.setValue('aa', 0);
    }
  }
  function updateTalking(dt) {
    if (!talking) return;
    talkT = (talkT + dt) % TALK_AA_PERIOD;
    const phase = talkT / TALK_AA_PERIOD; // 0..1
    const tri = phase < 0.5 ? phase * 2 : 2 - phase * 2; // 0→1→0
    vrm.expressionManager.setValue('aa', tri * TALK_AA_PEAK);
  }

  // （呼吸/idle/感情の身体挙動/ジェスチャーは updatePose に統合済み）

  // --- メインループ ---
  let disposed = false;
  const clock = new THREE.Clock();
  function loop() {
    if (disposed) return;
    requestAnimationFrame(loop);
    const dt = clock.getDelta();
    updateBlink();
    updateExpression(dt);
    updateTalking(dt);
    updatePose(dt, clock.elapsedTime);
    vrm.update(dt);
    renderer.render(scene, camera);
  }
  loop();

  function dispose() {
    if (disposed) return;
    disposed = true;
    try { ro?.disconnect(); } catch { /* noop */ }
    el.removeEventListener('pointerdown', onPointerDown);
    el.removeEventListener('pointermove', onPointerMove);
    el.removeEventListener('pointerup', onPointerUp);
    el.removeEventListener('pointercancel', onPointerUp);
    el.removeEventListener('wheel', onWheel);
    try {
      VRMUtils.deepDispose(vrm.scene);
    } catch { /* 古い three-vrm では deepDispose 無し */ }
    renderer.dispose();
    el.remove();
    container.innerHTML = '';
    delete container.__avatarHandle;
  }

  return { setExpression, setTalking, setPose, playGesture, dispose, __vrm: vrm };
}
