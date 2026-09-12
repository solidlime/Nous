/* =================================================================
   reset-to-default tests — defaults API → per-field reset buttons
   Covers: defaults fetch + cache, button injection, dirty detection,
   value/checkbox/radio/percent/effort/null transforms, and the
   guaranteed no-save behaviour.
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore } from '../core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

const DEFAULTS = {
  fields: {
    model: { default: '', help: 'モデル名', type: 'str', section: 'core' },
    base_url: { default: '', help: '接続先', type: 'str', section: 'core' },
    temperature: { default: 0.7, help: '温度', type: 'float', section: 'core' },
    top_p: { default: null, help: 'top_p', type: 'float', section: 'core' },
    reasoning_effort: { default: 'medium', help: '深さ', type: 'str', section: 'core' },
    context_compression_threshold: { default: 0.8, help: '閾値', type: 'float', section: 'context' },
    context_max_tokens: { default: null, help: '上限', type: 'int', section: 'context' },
    show_message_timestamps: { default: false, help: '時刻', type: 'bool', section: 'core' },
    brain_enrich_interval_seconds: { default: 60, help: '間隔', type: 'int', section: 'brain_simulation' },
    brain_spontaneous_interval_hours: { default: 1, help: '間隔', type: 'int', section: 'brain_simulation' },
    forgetting_decay_interval_seconds: { default: 3600, help: '間隔', type: 'int', section: 'forgetting' },
    voice_emotion_mode: { default: 'anchor', help: 'モード', type: 'str', section: 'voice' },
    voice_enabled: { default: false, help: '音声', type: 'bool', section: 'voice' },
    mcp_servers: { default: [], help: 'サーバー', type: 'list', section: 'tools' },
  },
};

let apiStub;

function buildForm() {
  document.body.innerHTML = `
    <div>
      <div><input type="range" id="chat-temperature" min="0" max="2" step="0.05" value="0.7" /></div>
      <div><input type="text" id="chat-model" value="" /></div>
      <div><input type="text" id="chat-base-url" value="https://api.example.com" /></div>
      <div><input type="range" id="chat-top-p" min="0" max="1" step="0.05" value="" /></div>
      <div><input type="number" id="chat-context-max-tokens" value="" /></div>
      <div><input type="range" id="chat-reasoning-effort" min="0" max="3" step="1" value="1" /></div>
      <div><input type="range" id="chat-compression-threshold" min="50" max="100" value="80" /></div>
      <div id="threshold-display">80%</div>
      <div><textarea id="chat-mcp-json"></textarea></div>
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <span>音声を有効化</span>
        <label class="toggle-switch"><input type="checkbox" id="chat-voice-enabled" /><span></span></label>
      </div>
      <div class="chat-check-row"><input type="checkbox" id="chat-show-timestamps" /><label for="chat-show-timestamps">ts</label></div>
      <div><input type="number" id="chat-brain-enrich-interval" value="" /></div>
      <div><input type="number" id="chat-brain-spontaneous-interval" value="" /></div>
      <div><input type="number" id="chat-forgetting-decay-interval-seconds" value="" /></div>
      <div>
        <label class="chat-inline-check"><input type="radio" name="chat-voice-emotion-mode" value="off" />off</label>
        <label class="chat-inline-check"><input type="radio" name="chat-voice-emotion-mode" value="anchor" checked />anchor</label>
        <label class="chat-inline-check"><input type="radio" name="chat-voice-emotion-mode" value="llm" />llm</label>
      </div>
    </div>`;
}

beforeAll(() => {
  loadCore();
  window.S = { persona: 'p1' };
  apiStub = vi.fn();
  window.Nous.Core.api = apiStub;
  window.Nous.Core.toast = window.Nous.Core.toast || (() => {});
  const code = readFileSync(resolve(__dirname, 'chat-settings.js'), 'utf-8');
  new Function(code)();
  const ST = window.Nous.Chat.settings;
  ST.renderMcpJson = () => {};
  ST.parseMcpJson = () => [];
  ST.updateSliderLabels = () => {};
  window.Nous.Chat.state = { mcpServers: [], enabledSkills: [], disabledTools: new Set() };
  window.Nous.Chat.tts = { checkConnection: () => {} };
});

beforeEach(() => {
  apiStub.mockReset();
  apiStub.mockResolvedValue(DEFAULTS);
  buildForm();
});

async function setup() {
  await window.Nous.Chat.settings.loadDefaults(true);
  window.Nous.Chat.settings.injectResetButtons();
}

const btn = (id) => document.querySelector('[data-reset-for="' + id + '"]');

describe('reset to default', () => {
  it('fetches defaults once and caches for the same persona', async () => {
    await window.Nous.Chat.settings.loadDefaults(true);
    await window.Nous.Chat.settings.loadDefaults();
    expect(apiStub).toHaveBeenCalledTimes(1);
    expect(apiStub.mock.calls[0][0]).toBe('/api/chat/p1/config/defaults');
  });

  it('injects a reset button per mapped field and wraps the input', async () => {
    await setup();
    expect(btn('chat-model')).not.toBeNull();
    expect(btn('chat-brain-enrich-interval')).not.toBeNull();
    expect(btn('chat-voice-emotion-mode')).not.toBeNull();
    expect(document.getElementById('chat-model').closest('.chat-reset-wrap')).not.toBeNull();
    // field help is surfaced from the defaults API, not hardcoded in JS
    expect(document.getElementById('chat-model').getAttribute('title')).toBe('モデル名');
  });

  it('flags a field dirty only when it diverges from the default', async () => {
    await setup();
    const model = document.getElementById('chat-model');
    model.value = 'custom';
    model.dispatchEvent(new Event('input', { bubbles: true }));
    expect(window.Nous.Chat.settings.isFieldDirty(['chat-model', 'model'])).toBe(true);
    expect(btn('chat-model').classList.contains('is-dirty')).toBe(true);

    model.value = '';
    model.dispatchEvent(new Event('input', { bubbles: true }));
    expect(btn('chat-model').classList.contains('is-dirty')).toBe(false);
  });

  it('resets a number to the API default without saving', async () => {
    await setup();
    const el = document.getElementById('chat-brain-enrich-interval');
    el.value = '999';
    window.Nous.Chat.settings.resetField('chat-brain-enrich-interval');
    expect(el.value).toBe('60');
    expect(apiStub.mock.calls.every((c) => !(c[1] && c[1].method === 'POST'))).toBe(true);
  });

  it('resets a range backed by a string enum to its index', async () => {
    await setup();
    const el = document.getElementById('chat-reasoning-effort');
    el.value = '3';
    window.Nous.Chat.settings.resetField('chat-reasoning-effort');
    expect(el.value).toBe('1'); // medium
  });

  it('resets a percent-backed field from a fraction default', async () => {
    await setup();
    const el = document.getElementById('chat-compression-threshold');
    el.value = '95';
    window.Nous.Chat.settings.resetField('chat-compression-threshold');
    expect(el.value).toBe('80');
  });

  it('resets a null default to an empty string', async () => {
    await setup();
    const el = document.getElementById('chat-context-max-tokens');
    el.value = '4096';
    window.Nous.Chat.settings.resetField('chat-context-max-tokens');
    expect(el.value).toBe('');
  });

  it('resets a checkbox to its boolean default', async () => {
    await setup();
    const el = document.getElementById('chat-show-timestamps');
    el.checked = true;
    window.Nous.Chat.settings.resetField('chat-show-timestamps');
    expect(el.checked).toBe(false);
  });

  it('resets a radio group to the default mode', async () => {
    await setup();
    document.querySelector('input[name="chat-voice-emotion-mode"][value="llm"]').checked = true;
    window.Nous.Chat.settings.resetField('chat-voice-emotion-mode');
    expect(document.querySelector('input[name="chat-voice-emotion-mode"]:checked').value).toBe('anchor');
  });

  it('clears the dirty flag after apply when the config matches defaults', async () => {
    await setup();
    const model = document.getElementById('chat-model');
    model.value = 'custom';
    model.dispatchEvent(new Event('input', { bubbles: true }));
    expect(btn('chat-model').classList.contains('is-dirty')).toBe(true);

    window.Nous.Chat.settings.apply({
      model: '',
      base_url: 'https://api.example.com',
      temperature: 0.7,
      brain_enrich_interval_seconds: 60,
    });
    expect(btn('chat-model').classList.contains('is-dirty')).toBe(false);
  });

  it('marks a loaded non-default range dirty from the first render', async () => {
    await window.Nous.Chat.settings.loadDefaults(true);
    window.Nous.Chat.settings.apply({
      base_url: 'https://api.example.com',
      temperature: 1.4,
    });
    window.Nous.Chat.settings.injectResetButtons();
    expect(btn('chat-temperature').classList.contains('is-dirty')).toBe(true);
  });

  it('tolerates float representation noise on a numeric field', async () => {
    await setup();
    const el = document.getElementById('chat-temperature');
    el.value = '0.7000000000000001';
    el.dispatchEvent(new Event('input', { bubbles: true }));
    expect(btn('chat-temperature').classList.contains('is-dirty')).toBe(false);
  });

  it('does not treat an unset (null-default) range as divergent', async () => {
    await setup();
    const el = document.getElementById('chat-top-p');
    el.value = '0.5'; // browser midpoint for the empty/unset range
    el.dispatchEvent(new Event('input', { bubbles: true }));
    expect(window.Nous.Chat.settings.isFieldDirty(['chat-top-p', 'top_p'])).toBe(false);
    expect(btn('chat-top-p').classList.contains('is-dirty')).toBe(false);
  });

  it('resets the MCP JSON editor to the default list', async () => {
    await setup();
    const el = document.getElementById('chat-mcp-json');
    el.value = '[{"name":"x"}]';
    expect(window.Nous.Chat.settings.isFieldDirty(['chat-mcp-json', 'mcp_servers', 'json'])).toBe(true);
    window.Nous.Chat.settings.resetField('chat-mcp-json');
    expect(JSON.parse(el.value)).toEqual([]);
  });

  it('places the icon per control type so it cannot overlap content', async () => {
    await setup();
    // range → icon sits beside the track (outside)
    expect(
      document.getElementById('chat-temperature').closest('.chat-reset-wrap')
        .classList.contains('chat-reset-wrap-outside'),
    ).toBe(true);
    // textarea → inner overlay with extra right padding for text + scrollbar
    expect(
      document.getElementById('chat-mcp-json').closest('.chat-reset-wrap')
        .classList.contains('chat-reset-wrap-textarea'),
    ).toBe(true);
    // text → plain inner overlay (padding reserves the icon's room)
    expect(document.getElementById('chat-model').closest('.chat-reset-wrap').className).toBe(
      'chat-reset-wrap',
    );
    // toggle switch → grouped with the switch, keeping the row right-aligned
    expect(
      document.getElementById('chat-voice-enabled').closest('.chat-reset-toggle-group'),
    ).not.toBeNull();
  });
});
