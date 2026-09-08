/* =================================================================
   brain simulation settings tests — 脳シミュレーションセクション
   Covers: load applies brain keys with contract defaults, collect
   sends the 10 brain_* keys, save→load round-trip, legacy
   memory_enrichment_auto_run/interval UI items are gone.
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
  'chat-brain-enrich-interval',
  'chat-brain-batch-limit',
  'chat-brain-novelty-sim',
  'chat-brain-novelty-importance',
  'chat-brain-novelty-multiplier',
  'chat-brain-emotion-gain-k',
  'chat-brain-rif-rho',
  'chat-brain-separation-threshold',
];

const BRAIN_CHECK_IDS = ['chat-brain-auto-run', 'chat-brain-graph-flash'];

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
    + '<input type="checkbox" id="chat-memory-enrichment-enabled" />'
    + '<input type="checkbox" id="chat-brain-llm-dedicated" />'
    + '<input type="checkbox" id="chat-brain-monologue" />'
    + '<input type="checkbox" id="chat-brain-reasoning" />'
    + '<input type="checkbox" id="chat-brain-spontaneous" />'
    + '<input type="number" id="chat-brain-spontaneous-interval" value="" />'
    + '<select id="chat-brain-reasoning-effort">'
    + '<option value="low">low</option><option value="medium">medium</option>'
    + '<option value="high">high</option><option value="max">max</option>'
    + '</select>'
    + '<input type="number" id="chat-brain-max-tokens" value="" />'
    + '<div id="chat-brain-llm-fields" class="settings-body-hidden">'
    + '<input type="text" id="chat-brain-llm-provider" value="" />'
    + '<input type="text" id="chat-brain-llm-model" value="" />'
    + '<input type="text" id="chat-brain-llm-base-url" value="" />'
    + '<input type="password" id="chat-brain-llm-api-key" value="" />'
    + '</div>';
  document.body.innerHTML = `<div>${html}${brains}</div>`;
}

beforeAll(() => {
  loadCore();
  window.S = { persona: 'p1' };
  // api stub must be in place before chat-settings.js captures C.api
  apiStub = vi.fn();
  window.Nous.Core.api = apiStub;
  window.Nous.Core.toast = window.Nous.Core.toast || (() => {});
  const code = readFileSync(resolve(__dirname, 'chat-settings.js'), 'utf-8');
  new Function(code)();
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
    expect(document.getElementById('chat-brain-enrich-interval').value).toBe('60');
    expect(document.getElementById('chat-brain-batch-limit').value).toBe('5');
    expect(document.getElementById('chat-brain-novelty-sim').value).toBe('0.75');
    expect(document.getElementById('chat-brain-novelty-importance').value).toBe('0.6');
    expect(document.getElementById('chat-brain-novelty-multiplier').value).toBe('2');
    expect(document.getElementById('chat-brain-emotion-gain-k').value).toBe('0.5');
    expect(document.getElementById('chat-brain-rif-rho').value).toBe('0.05');
    expect(document.getElementById('chat-brain-separation-threshold').value).toBe('0.75');
    expect(document.getElementById('chat-brain-auto-run').checked).toBe(false);
    expect(document.getElementById('chat-brain-graph-flash').checked).toBe(true);
  });

  it('collect sends the brain_* keys and drops the legacy enrichment auto/interval items', async () => {
    document.getElementById('chat-brain-auto-run').checked = true;
    const set = (id, v) => { document.getElementById(id).value = v; };
    set('chat-brain-enrich-interval', '90');
    set('chat-brain-batch-limit', '3');
    set('chat-brain-novelty-sim', '0.8');
    set('chat-brain-novelty-importance', '0.55');
    set('chat-brain-novelty-multiplier', '2.5');
    set('chat-brain-emotion-gain-k', '0.4');
    set('chat-brain-rif-rho', '0.1');
    set('chat-brain-separation-threshold', '0.8');
    document.getElementById('chat-brain-graph-flash').checked = false;

    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    expect(apiStub).toHaveBeenCalledTimes(1);
    const [url, opts] = apiStub.mock.calls[0];
    expect(url).toBe('/api/chat/p1/config');
    const body = JSON.parse(opts.body);
    expect(body.brain_enrich_auto_run).toBe(true);
    expect(body.brain_enrich_interval_seconds).toBe(90);
    expect(body.brain_enrich_batch_limit).toBe(3);
    expect(body.brain_novelty_sim_threshold).toBe(0.8);
    expect(body.brain_novelty_importance_threshold).toBe(0.55);
    expect(body.brain_novelty_stability_multiplier).toBe(2.5);
    expect(body.brain_emotion_gain_k).toBe(0.4);
    expect(body.brain_rif_suppression_rho).toBe(0.1);
    expect(body.brain_graph_flash_enabled).toBe(false);
    // dormant knob: not collected (merge API keeps the stored value)
    expect(body.brain_link_separation_threshold).toBeUndefined();
    // legacy auto-run/interval keys are replaced by the brain_* keys
    expect(body.memory_enrichment_auto_run).toBeUndefined();
    expect(body.memory_enrichment_interval).toBeUndefined();
    // the legacy UI inputs are gone from the section
    expect(document.getElementById('chat-memory-enrichment-auto-run')).toBeNull();
    expect(document.getElementById('chat-memory-enrichment-interval')).toBeNull();
  });

  it('save→load round-trip preserves the brain values', async () => {
    const set = (id, v) => { document.getElementById(id).value = v; };
    set('chat-brain-enrich-interval', '120');
    set('chat-brain-novelty-sim', '0.9');
    document.getElementById('chat-brain-auto-run').checked = true;
    document.getElementById('chat-brain-graph-flash').checked = false;

    const savedCfg = { brain_enrich_auto_run: true, brain_enrich_interval_seconds: 120,
      brain_novelty_sim_threshold: 0.9, brain_graph_flash_enabled: false };
    apiStub.mockResolvedValueOnce(savedCfg);
    await window.Nous.Chat.settings.save();
    window.Nous.Chat.settings.apply(savedCfg);
    expect(document.getElementById('chat-brain-enrich-interval').value).toBe('120');
    expect(document.getElementById('chat-brain-novelty-sim').value).toBe('0.9');
    expect(document.getElementById('chat-brain-auto-run').checked).toBe(true);
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

  it('REM monologue: round-trips brain_monologue_enabled through the checkbox', async () => {
    window.Nous.Chat.settings.apply({});
    expect(document.getElementById('chat-brain-monologue').checked).toBe(false);

    document.getElementById('chat-base-url').value = 'https://api.example.com';
    document.getElementById('chat-brain-monologue').checked = true;
    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    const body = JSON.parse(apiStub.mock.calls[0][1].body);
    expect(body.brain_monologue_enabled).toBe(true);

    const savedCfg = { brain_monologue_enabled: true };
    apiStub.mockResolvedValueOnce(savedCfg);
    window.Nous.Chat.settings.apply(savedCfg);
    expect(document.getElementById('chat-brain-monologue').checked).toBe(true);
  });
});

// ------------------------------------------------------------------
// Structural verification — the Python-rendered sidebar markup must
// keep every setting id (save/load contract) and the pipeline order:
// timing → monologue/introspection → LLM → gates → recall → visualize.
// ------------------------------------------------------------------
const BRAIN_PY = resolve(__dirname, '../../sections/chat/chat_sidebar_memory.py');

const BRAIN_IDS = [
  'chat-memory-enrichment-enabled',
  'chat-brain-auto-run',
  'chat-brain-enrich-interval',
  'chat-brain-batch-limit',
  'chat-brain-monologue',
  'chat-brain-spontaneous',
  'chat-brain-spontaneous-interval',
  'chat-brain-reasoning',
  'chat-brain-reasoning-effort',
  'chat-brain-max-tokens',
  'chat-brain-llm-dedicated',
  'chat-brain-llm-provider',
  'chat-brain-llm-model',
  'chat-brain-llm-base-url',
  'chat-brain-llm-api-key',
  'chat-brain-novelty-sim',
  'chat-brain-novelty-importance',
  'chat-brain-novelty-multiplier',
  'chat-brain-emotion-gain-k',
  'chat-brain-rif-rho',
  'chat-brain-separation-threshold',
  'chat-brain-graph-flash',
];

const BRAIN_SUBSECTION_ORDER = [
  '実行タイミング（REM）',
  '独り言・内省',
  'LLM',
  '学習ゲート',
  '想起と忘却',
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

  it('groups subsections in pipeline order (timing → monologue → llm → gates → recall → visualize)', () => {
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

  it('keeps the dedicated-llm toggle contract and the monologue toggle', () => {
    expect(src).toContain('id="chat-brain-llm-fields" class="settings-body-hidden"');
    expect(src).toContain('data-action="brain-llm-toggle"');
    expect(src).toContain('id="chat-brain-monologue"');
    expect(src).toContain('id="chat-brain-spontaneous"');
  });
});

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

  it('brain max tokens: load applies contract default 2048 and save sends the number', async () => {
    window.Nous.Chat.settings.apply({});
    expect(document.getElementById('chat-brain-max-tokens').value).toBe('2048');

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

  it('spontaneous introspection: OFF does not send interval, sends enabled=false', async () => {
    window.Nous.Chat.settings.apply({});
    expect(document.getElementById('chat-brain-spontaneous').checked).toBe(false);
    expect(document.getElementById('chat-brain-spontaneous-interval').value).toBe('6');

    document.getElementById('chat-base-url').value = 'https://api.example.com';
    apiStub.mockResolvedValueOnce({});
    await window.Nous.Chat.settings.save();
    const body = JSON.parse(apiStub.mock.calls[0][1].body);
    expect(body.brain_spontaneous_enabled).toBe(false);
    expect(body.brain_spontaneous_interval_hours).toBeUndefined();
  });

  it('spontaneous introspection: ON round-trips the 2 keys', async () => {
    document.getElementById('chat-base-url').value = 'https://api.example.com';
    document.getElementById('chat-brain-spontaneous').checked = true;
    document.getElementById('chat-brain-spontaneous-interval').value = '12';
    const savedCfg = { brain_spontaneous_enabled: true, brain_spontaneous_interval_hours: 12 };
    apiStub.mockResolvedValueOnce(savedCfg);
    await window.Nous.Chat.settings.save();
    const body = JSON.parse(apiStub.mock.calls[0][1].body);
    expect(body.brain_spontaneous_enabled).toBe(true);
    expect(body.brain_spontaneous_interval_hours).toBe(12);

    window.Nous.Chat.settings.apply(savedCfg);
    expect(document.getElementById('chat-brain-spontaneous').checked).toBe(true);
    expect(document.getElementById('chat-brain-spontaneous-interval').value).toBe('12');
  });
