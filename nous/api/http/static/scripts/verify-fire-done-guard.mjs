/* #057 直叩き検証: 本番実測と同じイベント順序 (hop_start → decision_bypass
   → hop_stop → converge×20) を流し、done ガード修正で終端表示が保たれるかを
   見る。vitest ハーネスは本環境で壊れている (fileURLToPath) ため jsdom 直使用。 */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { JSDOM } from 'jsdom';

const __dirname = dirname(fileURLToPath(import.meta.url)) + '/..';
const dom = new JSDOM('<!doctype html><html><body><section id="tab-graph"><div id="graph-content"></div></section></body></html>', {
  url: 'http://localhost/', pretendToBeVisual: true
});
const { window } = dom;
global.window = window;
global.document = window.document;
global.EventSource = window.EventSource = function () {
  this.readyState = 0;
  this.addEventListener = function () {};
  this.removeEventListener = function () {};
  this.close = function () {};
};
global.localStorage = window.localStorage;
global.requestAnimationFrame = (cb) => setTimeout(cb, 0);

function load(file) {
  const code = readFileSync(resolve(__dirname, file), 'utf-8');
  /* window.eval で実行して top-level var を window に置く（ブラウザの classic script と同じ。
     new Function だと var N / var api が閉包内に留まり jsdom 単体ではグローバル解決できない） */
  window.eval(code);
}

window.S = { persona: 'p1', tab: 'graph' };
load('core/namespace.js');
window.eval('var N = window.Nous; var S = window.S;');
load('core/constants.js');
load('core/dom.js');
load('core/time.js');
load('core/api.js');
load('core/sse.js');
load('features/graph.js');
const N = window.Nous;
const F = N.Features.GraphFire;

const RID = '0e9281a1-test-test-test';
const ev = (seq, kind, meta, source = '', target = '') =>
  ({ seq, kind, source, target, weight: 1.0, meta, ts: new Date().toISOString() });

const statusEl = document.getElementById('graph-fire-status');
const toggle = document.getElementById('graph-fire-toggle');
toggle.checked = true;
F.setMode(true);

/* runFire は vis-network を要求するため、セッションは手動で組む（handleFireEvent が検証対象） */
F.setMode(true);
const RID2 = '0e9281a1-test-test-test';
F._state().session = { requestId: RID2, hops: 2, decision: true, results: new Map(), memories: {}, hop: 0, done: false, bypassReason: '' };
const sessionId = F._state().session.requestId;

/* 本番実測 (/tmp/nas-wiring-tail.txt seq 70-92) と同一順序:
   bypass(71) → hop_stop(72) → converge(73-92) が後発。 */
F.handleFireEvent(ev(70, 'hop_start', { request_id: sessionId, hop: 1, turn_id: null }));
const dbg1 = { done: F._state().done, status: statusEl.textContent };
F.handleFireEvent(ev(71, 'decision_bypass', { request_id: sessionId, reason: 'judge_unavailable', hop: 1, turn_id: null }));
const dbg2 = { done: F._state().done, status: statusEl.textContent };
F.handleFireEvent(ev(72, 'hop_stop', { request_id: sessionId, reason: 'sufficiency', hop: 1, turn_id: null }));
const dbg3 = { done: F._state().done, status: statusEl.textContent };
console.log('hop_start後:', JSON.stringify(dbg1));
console.log('bypass後:', JSON.stringify(dbg2));
console.log('hop_stop後:', JSON.stringify(dbg3));
const terminalStatus = statusEl.textContent;
const doneAtStop = F._state().session.done;

/* 後発 converge 20件 (seq 73-92 相当) */
for (let i = 73; i <= 92; i++) {
  F.handleFireEvent(ev(i, 'converge', { request_id: sessionId, hop: 1, reason: 'sufficiency' },
    'memory_x' + i, 'memory_top'));
}

const after = {
  terminal: terminalStatus,
  doneAtStop,
  statusAfterConverge: statusEl.textContent,
  doneAfterConverge: F._state().session.done,
};

let pass = true;
if (!/十分性/.test(after.terminal)) { console.log('FAIL: hop_stop で終端表示にならない:', after.terminal); pass = false; }
if (!after.doneAtStop) { console.log('FAIL: hop_stop 後 done が false'); pass = false; }
if (after.statusAfterConverge !== after.terminal) {
  console.log('FAIL: 後発 converge が終端表示を上書きした:', after.statusAfterConverge);
  pass = false;
}
if (!after.doneAfterConverge) { console.log('FAIL: done が反転した'); pass = false; }

/* turn モード: 同ターン次 request の hop_start で再始動するか */
F.setTurnMode(true);
const st = F._state();
const turnSession = { turnId: 't1', requestId: null, hops: 2, decision: false, results: new Map(), memories: {}, hop: 0, done: false, bypassReason: '' };
st.session = turnSession;
st.turnMode = true;
F.handleFireEvent(ev(100, 'hop_start', { request_id: 'r-a', hop: 1, turn_id: 't1' }));
F.handleFireEvent(ev(101, 'hop_stop', { request_id: 'r-a', reason: 'max_hops', hop: 1, turn_id: 't1' }));
const turnDone1 = st.session.done;
F.handleFireEvent(ev(102, 'converge', { request_id: 'r-a', hop: 1, reason: 'max_hops' }, 'a', 'b'));
const keptAfterLate = st.session.done && /上限|hop/.test(statusEl.textContent);
F.handleFireEvent(ev(103, 'hop_start', { request_id: 'r-b', hop: 1, turn_id: 't1' }));
const rearmed = st.session.done === false;
console.log('turn: done@hop_stop=' + turnDone1 + ' lateConvergeIgnored=' + keptAfterLate + ' nextChainRearmed=' + rearmed);
if (!turnDone1 || !keptAfterLate || !rearmed) { console.log('FAIL: turn モード連鎖'); pass = false; }

console.log(pass ? 'ALL PASS' : 'FAILED');
process.exit(pass ? 0 : 1);
