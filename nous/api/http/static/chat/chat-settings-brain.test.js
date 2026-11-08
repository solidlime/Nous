/* =================================================================
   brain simulation settings tests — 脳シミュレーションセクション
   Covers: load applies brain keys with contract defaults, parallel
   sends the brain_* keys, save→load round-trip. Removed 2026-11-08:
   enrichment / spontaneous / novelty knobs (memory Enrichment 廃止).
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore } from '../core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

// ids saveChatConfig reads without optional chaining — the form must have them
const REQUIRED_SAVE_IDS = [
  ['input', 'chat-model', 'test-model'],
  ['input', 'chat-base-url', 'https://api.example.com'],
  ['input', 'chat-temperature', '0.7'],
  ['input', 'chat-max-tokens', '8192'],
  ['input', 'chat-stored-msgs', '200'],
  ['input', 'chat-context-max-tokens', ''],
  ['input', 'chat-compression-threshold', '80'],
  ['select', 'chat-compression-mode', 'auto'],
  ['input', 'chat-keep-recent', '2'],
  ['input', 'chat-compress-system', 'true'],
  ['input', 'chat-compress-history', 'true'],
  ['input', 'chat-memory-preload', '5'],
  ['input', 'chat-parallel-tools', 'true'],
  ['textarea', 'chat-system-prompt', ''],
  ['div', 'threshold-display', '80%'],
];

const BRAIN_NUM_IDS = [
  'chat-brain-emotion-gain-k',
  'chat-brain-separation-threshold',
  'chat-brain-reflection-retrieval-penalty',
  'chat-brain-reflection-injection-min-similarity',
  'chat-brain-reflection-injection-margin',
];

const BRAIN_CHECK_IDS = ['chat-brain-graph-flash'];

let apiStub;
let S;

function buildForm() {
  const html = REQUIRED_SAVE_IDS.map(([tag, id, v]) => {
    if (tag === 'select') {
      return `<select id="${id}"><option value="${v}">${v}</option></select>`;
    }
    if (tag === 'checkbox' || id.startsWith('chat-compress-')) {
      return `<input type="checkbox" id="${id}" ${v === 'true' ? 'checked' : ''} />`;
    }
    return `<${tag} id="${id}" value="${v}"></${tag}>`;
  }).join('');
  const brains = BRAIN_NUM_IDS.map((id) => `<input type="number" id="${id}" value="" />`).join('')
    + BRAIN_CHECK_IDS.map((id) => `<input type="checkbox" id="${id}" />`).join('')
    + '<input type="checkbox" id="chat-brain-llm-dedicated" />'
    + '<input type="checkbox" id="chat-brain-reasoning" />'
    + '<select id="chat-brain-reasoning-effort">'
    + '<option value="low">low</option><option value="medium">medium</option>'
    + '<option value="high">high</option><option value="max">max</option>'
    + '</select>'
    + '<input type="number" id="chat-brain-max-tokens" value="" />'
    + '<input type="checkbox" id="chat-brain-decision-enabled" />'
    + '<input type="text" id="chat-brain-decision-model" value="" />'
    + '<input type="range" id="chat-brain-decision-threshold" min="0" max="1" step="0.05" value="0.55" />'
    + '<select id="chat-brain-decision-max-hops">'
    + '<option value="1">1</option><option value="2">2</option>'
    + '<option value="3">3</option><option value="4">4</option>'
    + '<option value="5">5</option></select>'
    + '<input type="checkbox" id="chat-brain-decision-time-weight" />'
    + '<div id="chat-brain-llm-fields" class="settings-body-hidden">'
    + '<input type="text" id="chat-brain-llm-provider" value="" />'
    + '<input type="text" id="chat-brain-llm-model" value="" />'
    + '<input type="text" id="chat-brain-llm-base-url" value="" />'
    + '<input type="password" id="chat-brain-llm-api-key" value="" />'
    + '</div>'
    + '<input type="checkbox" id="chat-top-p-enabled" />'
    + '<input type="range" id="chat-top-p" min="0" max="1" step="0.05" value="1" disabled />'
    + '<input type="checkbox" id="chat-voice-streaming" checked />';
  document.body.innerHTML = `<div>${html}${brains}</div>`;
}

beforeAll(() => {
  loadCore();
  window.S = { persona: 'p1' };
  // api stub must be in place before chat-settings.js captures C.api
  apiStub = vi.fn();
  window.Nous.Core.api = apiStub;
  window.Nous.Core.toast = window.Nous.Core.toast || (() => {});
  // chat-settings.js split into settings/*.js — load chunks in order
  // (reader path only; test logic unchanged).
  for (const f of ['settings/reset.js', 'settings/apply.js', 'settings/apply-groups.js', 'settings/save.js']) {
    const code = readFileSync(resolve(__dirname, f), 'utf-8');
    new Function(code)();
  }
  S = window.S;
  const ST = window.Nous.Chat.settings;
  ST.renderMcpJson = () => {};
  ST.parseMcpJson = () => [];
  ST.updateSliderLabels = () => {};
  window.Nous.Chat.state = { mcpServers: [], enabledSkills: [], disabledTools: new Set() };
  window.Nous.Chat.tts = { checkConnection: () => {} };
  buildForm();
});

beforeEach(() => {
  apiStub.mockClear();
  apiStub.mockResolvedValue({});
  buildForm();
});

describe('brain simulation settings', () => {
  it('load applies contract defaults when config has no brain keys', () => {
    window.Nous.Chat.settings.apply({});
    expect(document.getElementById('chat-brain-emotion-gain-k').value).toBe('0.5');
    expect(document.getElementById('chat-brain-separation-threshold').value).toBe('0.75');
    expect(document.getElementById('chat-brain-graph-flash').checked).toBe(true);
  });

  it('collect sends the brain_* keys that remain after the enrichment removal', async () => {
    const set = (id, v) => { document.getElementById(id).value = v; };
    set('chat-brain-emotion-gain-k', '0.4');
    set('chat-brain-separation-threshold', '0.8');
    document.getElementById('chat-brain-graph-flash').checked = false;

    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    expect(apiStub).toHaveBeenCalledTimes(1);
    const [url, opts] = apiStub.mock.calls[0];
    expect(url).toBe('/api/chat/p1/config');
    const body = JSON.parse(opts.body);
    expect(body.brain_emotion_gain_k).toBe(0.4);
    expect(body.brain_graph_flash_enabled).toBe(false);
    // dormant knob: not collected (merge API keeps the stored value)
    expect(body.brain_link_separation_threshold).toBeUndefined();
    // enrichment knobs are gone from the save payload
    expect(body.memory_enrichment_enabled).toBeUndefined();
    expect(body.brain_enrich_auto_run).toBeUndefined();
    expect(body.brain_spontaneous_enabled).toBeUndefined();
    expect(body.brain_novelty_sim_threshold).toBeUndefined();
  });

  it('save→load round-trip preserves the brain values', async () => {
    const set = (id, v) => { document.getElementById(id).value = v; };
    set('chat-brain-emotion-gain-k', '0.3');
    document.getElementById('chat-brain-graph-flash').checked = false;

    const savedCfg = { brain_emotion_gain_k: 0.3,
      brain_graph_flash_enabled: false };
    apiStub.mockResolvedValueOnce(savedCfg);
    await window.Nous.Chat.settings.save();
    window.Nous.Chat.settings.apply(savedCfg);
    expect(document.getElementById('chat-brain-emotion-gain-k').value).toBe('0.3');
    expect(document.getElementById('chat-brain-graph-flash').checked).toBe(false);
  });

  it('dedicated LLM: OFF (default) hides the fields and sends only the toggle', async () => {
    window.Nous.Chat.settings.apply({});
    expect(document.getElementById('chat-brain-llm-dedicated').checked).toBe(false);
    expect(document.getElementById('chat-brain-llm-fields').classList.contains('settings-body-hidden')).toBe(true);

    apiStub.mockResolvedValueOnce({});
    // apply({}) clears chat-base-url (empty cfg) — restore the required field
    document.getElementById('chat-base-url').value = 'https://api.example.com';
    await window.Nous.Chat.settings.save();
    const body = JSON.parse(apiStub.mock.calls[0][1].body);
    expect(body.brain_llm_dedicated).toBe(false);
    // OFF: dedicated fields are not sent (merge API keeps stored values)
    expect(body.brain_llm_provider).toBeUndefined();
    expect(body.brain_llm_model).toBeUndefined();
    expect(body.brain_llm_base_url).toBeUndefined();
    expect(body.brain_llm_api_key).toBeUndefined();
  });

  it('dedicated LLM: ON round-trips the 5 keys and shows the fields', async () => {
    const set = (id, v) => { document.getElementById(id).value = v; };
    document.getElementById('chat-brain-llm-dedicated').checked = true;
    set('chat-brain-llm-provider', 'deepseek');
    set('chat-brain-llm-model', 'deepseek-v4');
    set('chat-brain-llm-base-url', 'https://api.deepseek.example/v1');
    set('chat-brain-llm-api-key', 'sk-brain');

    const savedCfg = { brain_llm_dedicated: true, brain_llm_provider: 'deepseek',
      brain_llm_model: 'deepseek-v4', brain_llm_base_url: 'https://api.deepseek.example/v1',
      brain_llm_api_key: 'sk-brain' };
    apiStub.mockResolvedValueOnce(savedCfg);
    await window.Nous.Chat.settings.save();
    const body = JSON.parse(apiStub.mock.calls[0][1].body);
    expect(body.brain_llm_dedicated).toBe(true);
    expect(body.brain_llm_provider).toBe('deepseek');
    expect(body.brain_llm_model).toBe('deepseek-v4');
    expect(body.brain_llm_base_url).toBe('https://api.deepseek.example/v1');
    expect(body.brain_llm_api_key).toBe('sk-brain');

    window.Nous.Chat.settings.apply(savedCfg);
    expect(document.getElementById('chat-brain-llm-dedicated').checked).toBe(true);
    expect(document.getElementById('chat-brain-llm-fields').classList.contains('settings-body-hidden')).toBe(false);
    expect(document.getElementById('chat-brain-llm-provider').value).toBe('deepseek');
    expect(document.getElementById('chat-brain-llm-model').value).toBe('deepseek-v4');
    expect(document.getElementById('chat-brain-llm-base-url').value).toBe('https://api.deepseek.example/v1');
    expect(document.getElementById('chat-brain-llm-api-key').value).toBe('sk-brain');
  });

  it('reflection injection margin: load applies contract default 0.08 and save round-trips it', async () => {
    window.Nous.Chat.settings.apply({});
    expect(document.getElementById('chat-brain-reflection-injection-margin').value).toBe('0.08');

    document.getElementById('chat-base-url').value = 'https://api.example.com';
    document.getElementById('chat-brain-reflection-injection-margin').value = '0.12';
    const savedCfg = { reflection_injection_margin: 0.12 };
    apiStub.mockResolvedValueOnce(savedCfg);
    await window.Nous.Chat.settings.save();
    const body = JSON.parse(apiStub.mock.calls[0][1].body);
    expect(body.reflection_injection_margin).toBe(0.12);

    window.Nous.Chat.settings.apply(savedCfg);
    expect(document.getElementById('chat-brain-reflection-injection-margin').value).toBe('0.12');
  });

  it('reflection injection margin: empty input is not sent (merge API keeps stored value)', async () => {
    window.Nous.Chat.settings.apply({});
    document.getElementById('chat-base-url').value = 'https://api.example.com';
    document.getElementById('chat-brain-reflection-injection-margin').value = '';
    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    const body = JSON.parse(apiStub.mock.calls[0][1].body);
    expect(body.reflection_injection_margin).toBeUndefined();
  });

  it('decision gate: load applies contract defaults and save round-trips the 4 keys', async () => {
    window.Nous.Chat.settings.apply({});
    expect(document.getElementById('chat-brain-decision-enabled').checked).toBe(false);
    expect(document.getElementById('chat-brain-decision-model').value).toBe('');
    expect(document.getElementById('chat-brain-decision-threshold').value).toBe('0.55');
    expect(document.getElementById('chat-brain-decision-max-hops').value).toBe('1');

    document.getElementById('chat-base-url').value = 'https://api.example.com';
    document.getElementById('chat-brain-decision-enabled').checked = true;
    document.getElementById('chat-brain-decision-model').value = 'gpt-x';
    document.getElementById('chat-brain-decision-threshold').value = '0.7';
    document.getElementById('chat-brain-decision-max-hops').value = '3';
    const savedCfg = { brain_decision_enabled: true, brain_decision_model: 'gpt-x',
      brain_decision_threshold: 0.7, brain_decision_max_hops: 3 };
    apiStub.mockResolvedValueOnce(savedCfg);
    await window.Nous.Chat.settings.save();
    const body = JSON.parse(apiStub.mock.calls[0][1].body);
    expect(body.brain_decision_enabled).toBe(true);
    expect(body.brain_decision_model).toBe('gpt-x');
    expect(body.brain_decision_threshold).toBe(0.7);
    expect(body.brain_decision_max_hops).toBe(3);

    window.Nous.Chat.settings.apply(savedCfg);
    expect(document.getElementById('chat-brain-decision-enabled').checked).toBe(true);
    expect(document.getElementById('chat-brain-decision-model').value).toBe('gpt-x');
    expect(document.getElementById('chat-brain-decision-threshold').value).toBe('0.7');
    expect(document.getElementById('chat-brain-decision-max-hops').value).toBe('3');
  });

  it('decision time weight: 0.0 → unchecked → 0.0(float) / 1.0 → checked → 1.0(float)', async () => {
    // 0.0 (既定) は unchecked。保存は bool ではなく float 0.0 を送る
    window.Nous.Chat.settings.apply({});
    expect(document.getElementById('chat-brain-decision-time-weight').checked).toBe(false);

    const postBodies = () => apiStub.mock.calls
      .filter((c) => c[1] && c[1].body)
      .map((c) => JSON.parse(c[1].body));

    document.getElementById('chat-base-url').value = 'https://api.example.com';
    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    let body = postBodies()[0];
    expect(body.brain_decision_time_weight).toBe(0.0);
    expect(typeof body.brain_decision_time_weight).toBe('number');

    // 1.0 → checked。保存値は float 1.0 (bool を送らない)
    document.getElementById('chat-base-url').value = 'https://api.example.com';
    document.getElementById('chat-brain-decision-time-weight').checked = true;
    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    body = postBodies().pop();
    expect(body.brain_decision_time_weight).toBe(1.0);
    expect(typeof body.brain_decision_time_weight).toBe('number');

    // API で 0.5 が入っていても「値に依らず有効」= checked
    window.Nous.Chat.settings.apply({ brain_decision_time_weight: 0.5 });
    expect(document.getElementById('chat-brain-decision-time-weight').checked).toBe(true);
  });

  it('voice_streaming: apply reflects it and save round-trips true/false', async () => {
    window.Nous.Chat.settings.apply({ voice_streaming: false });
    expect(document.getElementById('chat-voice-streaming').checked).toBe(false);
    window.Nous.Chat.settings.apply({});
    expect(document.getElementById('chat-voice-streaming').checked).toBe(true);

    document.getElementById('chat-base-url').value = 'https://api.example.com';
    document.getElementById('chat-voice-streaming').checked = true;
    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    expect(JSON.parse(apiStub.mock.calls[0][1].body).voice_streaming).toBe(true);

    document.getElementById('chat-base-url').value = 'https://api.example.com';
    document.getElementById('chat-voice-streaming').checked = false;
    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    expect(JSON.parse(apiStub.mock.calls[1][1].body).voice_streaming).toBe(false);
  });

  it('top_p: unchecked sends null, checked sends the parsed value', async () => {
    window.Nous.Chat.settings.apply({});
    const postBodies = () => apiStub.mock.calls
      .filter((c) => c[1] && c[1].body)
      .map((c) => JSON.parse(c[1].body));

    // unset → null
    document.getElementById('chat-base-url').value = 'https://api.example.com';
    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    expect(postBodies()[0].top_p).toBeNull();

    // enabled → numeric value (save's apply() reset the form, so re-arm it)
    document.getElementById('chat-base-url').value = 'https://api.example.com';
    document.getElementById('chat-top-p-enabled').checked = true;
    document.getElementById('chat-top-p').value = '0.9';
    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    expect(postBodies()[1].top_p).toBe(0.9);
  });
});

// ------------------------------------------------------------------
// Structural verification — the Python-rendered sidebar markup must
// keep every setting id (save/load contract) and the pipeline order:
// LLM → gates → recall → visualize.
// ------------------------------------------------------------------
const BRAIN_PY = resolve(__dirname, '../../sections/chat/chat_sidebar_memory.py');

const BRAIN_IDS = [
  'chat-brain-reasoning',
  'chat-brain-reasoning-effort',
  'chat-brain-max-tokens',
  'chat-brain-llm-dedicated',
  'chat-brain-llm-provider',
  'chat-brain-llm-model',
  'chat-brain-llm-base-url',
  'chat-brain-llm-api-key',
  'chat-brain-emotion-gain-k',
  'chat-brain-separation-threshold',
  'chat-brain-reflection-retrieval-penalty',
  'chat-brain-reflection-injection-min-similarity',
  'chat-brain-reflection-injection-margin',
  'chat-brain-graph-flash',
  'chat-brain-decision-enabled',
  'chat-brain-decision-model',
  'chat-brain-decision-threshold',
  'chat-brain-decision-max-hops',
  'chat-brain-decision-time-weight',
];

const BRAIN_SUBSECTION_ORDER = [
  'LLM',
  '学習ゲート',
  '想起と忘却',
  '判定ゲート（Jev型）',
  '可視化',
];

describe('brain section structure (chat_sidebar_memory.py)', () => {
  let src;
  beforeAll(() => {
    src = readFileSync(BRAIN_PY, 'utf-8');
  });

  it('renders every setting id exactly once (save/load contract intact)', () => {
    for (const id of BRAIN_IDS) {
      const hits = src.split('id="' + id + '"').length - 1;
      expect(hits).toBe(1);
    }
  });

  it('keeps the brain_simulation category and its help-icon wiring', () => {
    expect(src).toContain('<details data-category="brain_simulation">');
    expect(src).toContain('data-category="brain_simulation" tabindex="0"');
  });

  it('groups subsections in pipeline order (llm → gates → recall → visualize)', () => {
    const block = src.slice(src.indexOf('<details data-category="brain_simulation">'));
    let pos = -1;
    for (const label of BRAIN_SUBSECTION_ORDER) {
      const next = block.indexOf('<summary>' + label + '</summary>');
      expect(next).toBeGreaterThan(pos);
      pos = next;
    }
    // legacy flat grouping is gone
    expect(block).not.toContain('<summary>記憶強化（REM）</summary>');
    expect(block).not.toContain('<summary>専用 LLM</summary>');
  });

  it('keeps the dedicated-llm toggle contract', () => {
    expect(src).toContain('id="chat-brain-llm-fields" class="settings-body-hidden"');
    expect(src).toContain('data-action="brain-llm-toggle"');
  });
});

describe('brain simulation apply/save', () => {
  it('brain reasoning: OFF (default) does not send effort, sends enabled=false', async () => {
    window.Nous.Chat.settings.apply({});
    expect(document.getElementById('chat-brain-reasoning').checked).toBe(false);
    expect(document.getElementById('chat-brain-reasoning-effort').value).toBe('medium');

    document.getElementById('chat-base-url').value = 'https://api.example.com';
    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    const body = JSON.parse(apiStub.mock.calls[0][1].body);
    expect(body.brain_reasoning_enabled).toBe(false);
    // OFF: effort is not sent (merge API keeps the stored value)
    expect(body.brain_reasoning_effort).toBeUndefined();
  });

  it('brain reasoning: ON round-trips the 2 keys', async () => {
    document.getElementById('chat-base-url').value = 'https://api.example.com';
    document.getElementById('chat-brain-reasoning').checked = true;
    document.getElementById('chat-brain-reasoning-effort').value = 'high';
    const savedCfg = { brain_reasoning_enabled: true, brain_reasoning_effort: 'high' };
    apiStub.mockResolvedValueOnce(savedCfg);
    await window.Nous.Chat.settings.save();
    const body = JSON.parse(apiStub.mock.calls[0][1].body);
    expect(body.brain_reasoning_enabled).toBe(true);
    expect(body.brain_reasoning_effort).toBe('high');

    window.Nous.Chat.settings.apply(savedCfg);
    expect(document.getElementById('chat-brain-reasoning').checked).toBe(true);
    expect(document.getElementById('chat-brain-reasoning-effort').value).toBe('high');
  });

  it('brain max tokens: load applies contract default 0 (inherit) and save sends the number', async () => {
    window.Nous.Chat.settings.apply({});
    expect(document.getElementById('chat-brain-max-tokens').value).toBe('0');

    document.getElementById('chat-base-url').value = 'https://api.example.com';
    document.getElementById('chat-brain-max-tokens').value = '4096';
    const savedCfg = { brain_max_tokens: 4096 };
    apiStub.mockResolvedValueOnce(savedCfg);
    await window.Nous.Chat.settings.save();
    const body = JSON.parse(apiStub.mock.calls[0][1].body);
    expect(body.brain_max_tokens).toBe(4096);

    window.Nous.Chat.settings.apply(savedCfg);
    expect(document.getElementById('chat-brain-max-tokens').value).toBe('4096');
  });

  it('brain max tokens: empty input is not sent (merge API keeps stored value)', async () => {
    window.Nous.Chat.settings.apply({});
    document.getElementById('chat-base-url').value = 'https://api.example.com';
    document.getElementById('chat-brain-max-tokens').value = '';
    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    const body = JSON.parse(apiStub.mock.calls[0][1].body);
    expect(body.brain_max_tokens).toBeUndefined();
  });
});
