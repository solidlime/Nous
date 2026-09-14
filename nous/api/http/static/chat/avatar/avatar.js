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
const easeInOut = (t) => t * t * (3 - 2 * t);

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
  return { setExpression: nop, setTalking: nop, dispose: nop, __fallback: true };
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
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.combineSkeletons(gltf.scene);
    scene.add(vrm.scene);
    vrm.lookAt.target = lookAtTarget;
    vrm.springBoneManager?.reset();

    // A ポーズ: 上腕を下ろす
    const lArm = vrm.humanoid.getNormalizedBoneNode('leftUpperArm');
    const rArm = vrm.humanoid.getNormalizedBoneNode('rightUpperArm');
    if (lArm) lArm.rotation.z = THREE.MathUtils.degToRad(-70);
    if (rArm) rArm.rotation.z = THREE.MathUtils.degToRad(70);
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

  // --- 呼吸 + idle 揺れ ---
  function updateIdle(elapsed) {
    const spine = vrm.humanoid.getNormalizedBoneNode('spine');
    if (spine) spine.rotation.z = THREE.MathUtils.degToRad(1.5 * Math.sin((elapsed * Math.PI * 2) / 4));
    const head = vrm.humanoid.getNormalizedBoneNode('head');
    if (head) {
      head.rotation.x = THREE.MathUtils.degToRad(0.8 * Math.sin(elapsed * 0.6));
      head.rotation.y = THREE.MathUtils.degToRad(1.2 * Math.sin(elapsed * 0.4 + 1.7));
    }
  }

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
    updateIdle(clock.elapsedTime);
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

  return { setExpression, setTalking, dispose };
}
