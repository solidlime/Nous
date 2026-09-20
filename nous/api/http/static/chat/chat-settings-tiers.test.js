/* =================================================================
   3-tier settings visibility tests — basic / advanced / expert
   Covers: expert layer hidden by default, header toggle reveals it
   (+ localStorage persistence), missing/unknown tier falls back to
   hidden (fail-safe), and the help text surfaced as title.
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore } from '../core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

const STORAGE_KEY = 'nous.chat.settings.showExpert';
const HIDDEN = 'chat-tier-hidden';

// Defaults stub with tiers: basic / advanced / expert / unknown / missing.
// chat-mental-model-min-samples is intentionally absent → "no tier" case.
const DEFAULTS = {
  fields: {
    model: { default: '', help: 'モデル名', tier: 'basic' },
    top_p: { default: null, help: 'Top P の上限', tier: 'advanced' },
    brain_novelty_sim_threshold: {
      default: 0.75,
      help: '新規性ゲート（効く条件: 新規記憶の定着判定のみ）',
      tier: 'expert',
    },
    brain_emotion_gain_k: { default: 0.5, help: '感情 gain', tier: 'wizard' },
    voice_emotion_mode: { default: 'anchor', help: '感情の反映モード', tier: 'expert' },
  },
};

let apiStub;

function buildForm() {
  document.body.innerHTML = `
    <div id="settings-panel">
      <div id="chat-config-status"></div>
      <div class="settings-scroll-container">
        <label class="chat-expert-toggle" for="chat-settings-show-expert">
          <input type="checkbox" id="chat-settings-show-expert" />
          <span>詳細設定を表示</span>
        </label>
        <div><div class="chat-field-label">モデル</div><input type="text" id="chat-model" value="" /></div>
        <div><div class="chat-field-label">Top P</div><input type="range" id="chat-top-p" value="1" /></div>
        <div class="chat-check-row"><input type="checkbox" id="chat-top-p-enabled" /><label for="chat-top-p-enabled">Top P を指定する</label></div>
        <div><div class="chat-field-label">新規性 類似度しきい値</div><input type="number" id="chat-brain-novelty-sim" value="0.75" /></div>
        <div><div class="chat-field-label">感情 gain 係数 k</div><input type="number" id="chat-brain-emotion-gain-k" value="0.5" /></div>
        <div><div class="chat-field-label">最小サンプル数</div><input type="number" id="chat-mental-model-min-samples" value="3" /></div>
        <div>
          <div class="chat-field-label">感情の反映</div>
          <div style="display:flex;flex-direction:column;gap:4px;">
            <label class="chat-inline-check"><input type="radio" name="chat-voice-emotion-mode" value="off" />off</label>
            <label class="chat-inline-check"><input type="radio" name="chat-voice-emotion-mode" value="anchor" checked />anchor</label>
            <label class="chat-inline-check"><input type="radio" name="chat-voice-emotion-mode" value="llm" />llm</label>
          </div>
        </div>
      </div>
    </div>`;
}

const rowOf = (id) => document.getElementById(id).parentElement;
const isHidden = (id) => rowOf(id).classList.contains(HIDDEN);
const toggle = () => document.getElementById('chat-settings-show-expert');

beforeAll(() => {
  loadCore();
  window.S = { persona: 'p1' };
  apiStub = vi.fn();
  window.Nous.Core.api = apiStub;
  window.Nous.Core.toast = window.Nous.Core.toast || (() => {});
  for (const f of [
    'settings/reset.js',
    'settings/apply.js',
    'settings/apply-groups.js',
    'settings/save.js',
  ]) {
    const code = readFileSync(resolve(__dirname, f), 'utf-8');
    new Function(code)();
  }
  const ST = window.Nous.Chat.settings;
  ST.renderMcpJson = () => {};
  ST.parseMcpJson = () => [];
  ST.updateSliderLabels = () => {};
  window.Nous.Chat.state = { mcpServers: [], enabledSkills: [], disabledTools: new Set() };
  window.Nous.Chat.tts = { checkConnection: () => {} };
});

beforeEach(() => {
  window.localStorage.clear();
  apiStub.mockReset();
  apiStub.mockResolvedValue(DEFAULTS);
  buildForm();
});

async function setup() {
  await window.Nous.Chat.settings.loadDefaults(true);
  window.Nous.Chat.settings.applyFieldTiers();
}

describe('3-tier settings visibility', () => {
  it('hides the expert layer by default and keeps basic/advanced visible', async () => {
    await setup();
    expect(window.Nous.Chat.settings.tierOf('brain_novelty_sim_threshold')).toBe('expert');
    expect(isHidden('chat-brain-novelty-sim')).toBe(true);
    expect(isHidden('chat-model')).toBe(false);
    expect(isHidden('chat-top-p')).toBe(false);
    expect(toggle().checked).toBe(false);
  });

  it('reveals the expert layer with the header toggle and persists the state', async () => {
    await setup();
    const t = toggle();
    t.checked = true;
    t.dispatchEvent(new Event('change', { bubbles: true }));

    expect(isHidden('chat-brain-novelty-sim')).toBe(false);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('1');

    // fresh init (reload) honours the stored state
    buildForm();
    window.Nous.Chat.settings.applyFieldTiers();
    expect(toggle().checked).toBe(true);
    expect(isHidden('chat-brain-novelty-sim')).toBe(false);

    // turning it off hides again (expert layer stays off by default)
    toggle().checked = false;
    toggle().dispatchEvent(new Event('change', { bubbles: true }));
    expect(isHidden('chat-brain-novelty-sim')).toBe(true);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('0');
  });

  it('treats a missing or unknown tier as expert (fail-safe: hidden)', async () => {
    await setup();
    // unknown tier string
    expect(window.Nous.Chat.settings.tierOf('brain_emotion_gain_k')).toBe('expert');
    expect(isHidden('chat-brain-emotion-gain-k')).toBe(true);
    // key absent from the defaults payload entirely
    expect(window.Nous.Chat.settings.tierOf('mental_model_min_samples')).toBe('expert');
    expect(isHidden('chat-mental-model-min-samples')).toBe(true);
  });

  it('hides an expert radio group whole and titles its options from help', async () => {
    await setup();
    const radio = document.querySelector('input[name="chat-voice-emotion-mode"]');
    expect(radio.closest('.' + HIDDEN)).not.toBeNull();
    expect(radio.getAttribute('title')).toBe('感情の反映モード');

    const t = toggle();
    t.checked = true;
    t.dispatchEvent(new Event('change', { bubbles: true }));
    expect(radio.closest('.' + HIDDEN)).toBeNull();
  });

  it('exposes fields[name].help on the control as a title', async () => {
    await setup();
    expect(document.getElementById('chat-brain-novelty-sim').getAttribute('title')).toBe(
      '新規性ゲート（効く条件: 新規記憶の定着判定のみ）',
    );
    expect(document.getElementById('chat-model').getAttribute('title')).toBe('モデル名');
  });
});

describe('settings load wiring (init path)', () => {
  // Regression: loadChatConfig() called the reset.js closure-local
  // `loadConfigDefaults()` as a bare identifier.  That function only exists
  // inside reset.js's IIFE (exported as N.Chat.settings.loadDefaults), so the
  // call threw "loadConfigDefaults is not defined" OUTSIDE the try block:
  // the whole settings load died silently — defaults were never fetched, the
  // per-field reset buttons were never injected and the 3-tier gating never
  // ran (the panel only looked fine because the server renders field values).
  // Driving the real entry point (N.Chat.settings.load) keeps that dead-call
  // class of bug from coming back.
  it('load() reaches the defaults API (the bare-identifier call is gone)', async () => {
    // persona を変えて defaults キャッシュ（persona 単位）をミスさせる
    window.S.persona = 'wiring-regression';
    apiStub.mockImplementation((url) =>
      String(url).includes('/config/defaults')
        ? Promise.resolve(DEFAULTS)
        : Promise.resolve({ model: 'm1', temperature: 0.7 }),
    );

    // At HEAD this rejected before any fetch: the ReferenceError happened on the
    // line above the API calls, so "was the defaults endpoint even requested?"
    // is the falsifiable signal for this regression.
    await window.Nous.Chat.settings.load();

    const urls = apiStub.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes('/config/defaults'))).toBe(true);
    expect(urls.some((u) => /\/config$/.test(u))).toBe(true);
  });

  it('load() surfaces an API failure in #chat-config-status instead of failing silently', async () => {
    apiStub.mockRejectedValue(new Error('boom'));

    await window.Nous.Chat.settings.load();

    expect(document.getElementById('chat-config-status').textContent).toContain('設定読込失敗');
    expect(document.getElementById('chat-config-status').textContent).toContain('boom');
  });
});
