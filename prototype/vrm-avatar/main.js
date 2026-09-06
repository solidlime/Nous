import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

function showError(msg) {
  const el = document.getElementById('err');
  el.hidden = false;
  el.textContent = msg;
}

function checkWebGL() {
  try {
    const canvas = document.createElement('canvas');
    return !!(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

if (!checkWebGL()) {
  showError('WebGL is not available in this browser.');
  throw new Error('WebGL unavailable');
}

window.onerror = (msg, src, line, col) => {
  showError(`Error: ${msg}\n${src}:${line}:${col}`);
};

const overlay = document.getElementById('overlay');

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.getElementById('app').appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x202024);

const camera = new THREE.PerspectiveCamera(30, window.innerWidth / window.innerHeight, 0.1, 50);
camera.position.set(0, 1.4, 2.6);
camera.lookAt(0, 1.2, 0);

const dirLight = new THREE.DirectionalLight(0xffffff, Math.PI * 0.8);
dirLight.position.set(1.5, 3, 2);
scene.add(dirLight);
scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x40382f, Math.PI * 0.55));

// lookAt ターゲットはカメラ方向
const lookAtTarget = new THREE.Object3D();
lookAtTarget.position.copy(camera.position);
scene.add(lookAtTarget);

let vrm = null;
const mixer = null;

try {
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));

  const gltf = await new Promise((resolve, reject) => {
    loader.load('./models/sample.vrm', resolve, undefined, reject);
  });

  vrm = gltf.userData.vrm;
  VRMUtils.removeUnnecessaryVertices(gltf.scene);
  VRMUtils.combineSkeletons(gltf.scene);
  scene.add(vrm.scene);
  vrm.lookAt.target = lookAtTarget;
  vrm.springBoneManager?.reset();

  // A ポーズ (rest pose): normalized bone の identity は T ポーズなので上腕を下げる
  const lArm = vrm.humanoid.getNormalizedBoneNode('leftUpperArm');
  const rArm = vrm.humanoid.getNormalizedBoneNode('rightUpperArm');
  if (lArm) lArm.rotation.z = THREE.MathUtils.degToRad(-70);
  if (rArm) rArm.rotation.z = THREE.MathUtils.degToRad(70);

  overlay.textContent = 'neutral';
} catch (e) {
  showError(`Failed to load VRM model: ${e?.message ?? e}`);
  throw e;
}

window.__avatarState = { vrm, mixer, expressionManager: vrm.expressionManager };

// --- まばたき: time-based ランダムスケジューラ ---
const blink = { next: 2 + Math.random() * 6, w: 0, phase: null };
const BLINK_HALF = 0.1; // 100ms each way

// --- 表情サイクル: 3秒ごとに主表情を切替、0.4秒で遷移 ---
const EMOTIONS = ['happy', 'surprised', 'sad', 'angry', 'relaxed', 'neutral'];
const CYCLE = 3, FADE = 0.4, PEAK = 0.7;
let emotionIdx = 0, cycleT = 0, fade = { from: 0, weight: 0, name: EMOTIONS[0] };
const easeInOut = (t) => t * t * (3 - 2 * t);

function setEmotion(name, weight) {
  for (const e of EMOTIONS) {
    vrm.expressionManager.setValue(e, e === name ? weight : 0);
  }
  overlay.textContent = name;
}

function updateExpressions(dt) {
  cycleT += dt;
  if (cycleT >= CYCLE) {
    cycleT = 0;
    emotionIdx = (emotionIdx + 1) % EMOTIONS.length;
    fade = { from: fade.weight, weight: fade.weight, name: EMOTIONS[emotionIdx] };
  }
  const target = EMOTIONS[emotionIdx];
  // 現在の weight をキャプチャして 0.4 秒で easeInOut 遷移
  if (cycleT < FADE) {
    const t = easeInOut(cycleT / FADE);
    fade.weight = fade.from + (PEAK - fade.from) * t;
  } else {
    fade.weight = PEAK;
  }
  setEmotion(fade.name, fade.weight);
}

function updateIdle(elapsed) {
  const spine = vrm.humanoid.getNormalizedBoneNode('spine');
  // 呼吸: spine を ±1.5 度・周期約4秒で
  spine.rotation.z = THREE.MathUtils.degToRad(1.5 * Math.sin((elapsed * Math.PI * 2) / 4));
  const head = vrm.humanoid.getNormalizedBoneNode('head');
  // 頭: 低周波の微小な揺れ
  head.rotation.x = THREE.MathUtils.degToRad(0.8 * Math.sin(elapsed * 0.6));
  head.rotation.y = THREE.MathUtils.degToRad(1.2 * Math.sin(elapsed * 0.4 + 1.7));
}

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
      // 0→1→0 を線形 lerp (各100ms)
      blink.w = p <= 1 ? p : 2 - p;
    }
  }
  vrm.expressionManager.setValue('blink', blink.w);
}

const clock = new THREE.Clock();
function loop() {
  requestAnimationFrame(loop);
  const dt = clock.getDelta();
  const elapsed = clock.elapsedTime;
  if (vrm) {
    updateBlink();
    updateExpressions(dt);
    updateIdle(dt, elapsed);
    vrm.update(dt);
  }
  renderer.render(scene, camera);
}
loop();

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
