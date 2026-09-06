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
    + '<input type="checkbox" id="chat-memory-enrichment-enabled" />';
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
});
