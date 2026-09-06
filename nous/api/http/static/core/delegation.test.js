/* =================================================================
   Tests for core/delegation.js — CSP-safe receivers for
   server-rendered templates (data-* + delegated addEventListener).
   Loads ONLY namespace.js + delegation.js with stubbed N.* namespaces.
   ================================================================= */
import { loadCore, loadFile } from './load-core.js';

const DOM = `
<img id="chat-persona-avatar" src="" alt="">
<button data-action="chat-send" id="b-send">send</button>
<button data-action="chat-toggle-next" id="b-next">adv</button><div id="nx" style="display:none">x</div>
<div data-action="chat-close-viewer" id="ov"><div id="media-viewer-inner"><span id="ov-in">x</span></div></div>
<div data-action="mem-edit-backdrop" id="bd"><span id="bd-in">x</span></div>
<input id="m-fixed2" data-mirror="t-fixed2" data-mirror-format="fixed2" value="0.7"><span id="t-fixed2"></span>
<input id="m-topP" data-mirror="t-topP" data-mirror-format="topP" value=""><span id="t-topP"></span>
<input id="m-effort" data-mirror="t-effort" data-mirror-format="effort" value="2"><span id="t-effort"></span>
<input id="m-pct" data-mirror="t-pct" data-mirror-format="percent" value="0.5"><span id="t-pct"></span>
<input id="m-raw" data-mirror="t-raw" value="4000"><span id="t-raw"></span>
<input id="m-sfx" data-mirror="t-sfx" data-mirror-format="fixed2" data-mirror-suffix="x" value="1"><span id="t-sfx"></span>
<input type="checkbox" id="c-dis" data-toggle-target="dis-target" data-toggle-mode="disabled" checked><input id="dis-target">
<input type="radio" id="r-disp" data-toggle-target="disp-target" data-toggle-mode="display" data-toggle-value="block"><div id="disp-target" style="display:none"></div>
<form data-password-form="t"><input type="password" id="pw"></form>`;

function click(el) {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
}

function input(el) {
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

function change(el) {
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

beforeAll(() => {
  loadCore();
  const N = window.Nous;
  N.Chat = {
    send: vi.fn(),
    cancel: vi.fn(),
    core: { toggleSettings: vi.fn(), toggleMemory: vi.fn() },
    attachments: { trigger: vi.fn(), closeViewer: vi.fn() },
    voice: { toggle: vi.fn() },
    history: { export: vi.fn(), clear: vi.fn() },
    settings: { save: vi.fn(), formatMcpJson: vi.fn(), testImageGen: vi.fn() },
    tts: { test: vi.fn() },
  };
  N.Features = {
    Memories: { closeEditModal: vi.fn(), saveMemory: vi.fn() },
    Timeline: { loadTimeline: vi.fn() },
    Activity: { loadActivity: vi.fn() },
  };
  document.body.innerHTML = DOM;
  loadFile('delegation.js');
});

describe('delegation click routing', () => {
  it('routes data-action clicks to N.* receivers', () => {
    click(document.getElementById('b-send'));
    expect(window.Nous.Chat.send).toHaveBeenCalledTimes(1);
  });

  it('passes true to loadActivity on refresh', () => {
    const btn = document.createElement('button');
    btn.setAttribute('data-action', 'act-refresh');
    document.body.appendChild(btn);
    click(btn);
    expect(window.Nous.Features.Activity.loadActivity).toHaveBeenCalledWith(true);
    btn.remove();
  });

  it('toggles next-sibling display (exact inline-style parity)', () => {
    const nx = document.getElementById('nx');
    expect(nx.style.display).toBe('none');
    click(document.getElementById('b-next'));
    expect(nx.style.display).toBe('');
    click(document.getElementById('b-next'));
    expect(nx.style.display).toBe('none');
  });

  it('closes viewer on overlay click but not on inner-content click', () => {
    click(document.getElementById('ov-in'));
    expect(window.Nous.Chat.attachments.closeViewer).not.toHaveBeenCalled();
    click(document.getElementById('ov'));
    expect(window.Nous.Chat.attachments.closeViewer).toHaveBeenCalledTimes(1);
  });

  it('closes edit modal on backdrop click only (exact-target parity)', () => {
    click(document.getElementById('bd-in'));
    expect(window.Nous.Features.Memories.closeEditModal).not.toHaveBeenCalled();
    click(document.getElementById('bd'));
    expect(window.Nous.Features.Memories.closeEditModal).toHaveBeenCalledTimes(1);
  });
});

describe('delegation mirrors', () => {
  it('formats fixed2 / topP-NaN / effort / percent / raw / suffix', () => {
    input(document.getElementById('m-fixed2'));
    expect(document.getElementById('t-fixed2').textContent).toBe('0.70');
    input(document.getElementById('m-topP'));
    expect(document.getElementById('t-topP').textContent).toBe('—');
    input(document.getElementById('m-effort'));
    expect(document.getElementById('t-effort').textContent).toBe('high');
    input(document.getElementById('m-pct'));
    expect(document.getElementById('t-pct').textContent).toBe('50%');
    const raw = document.getElementById('m-raw');
    raw.value = '8000';
    input(raw);
    expect(document.getElementById('t-raw').textContent).toBe('8000');
    input(document.getElementById('m-sfx'));
    expect(document.getElementById('t-sfx').textContent).toBe('1.00x');
  });
});

describe('delegation toggles', () => {
  it('flips disabled from checkbox state', () => {
    const box = document.getElementById('c-dis');
    const target = document.getElementById('dis-target');
    box.checked = false;
    change(box);
    expect(target.disabled).toBe(true);
    box.checked = true;
    change(box);
    expect(target.disabled).toBe(false);
  });

  it('sets display value when the radio becomes checked', () => {
    const radio = document.getElementById('r-disp');
    const target = document.getElementById('disp-target');
    radio.checked = true;
    change(radio);
    expect(target.style.display).toBe('block');
  });
});

describe('delegation forms + avatar', () => {
  it('prevents password-form submit (no reload)', () => {
    const form = document.querySelector('[data-password-form]');
    const ev = new Event('submit', { bubbles: true, cancelable: true });
    form.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
  });

  it('hides avatar with empty src at init', () => {
    expect(document.getElementById('chat-persona-avatar').style.display).toBe('none');
  });

  it('shows avatar on load, hides on error', () => {
    const avatar = document.getElementById('chat-persona-avatar');
    avatar.setAttribute('src', 'http://example.invalid/x.png');
    avatar.dispatchEvent(new Event('load'));
    expect(avatar.style.display).toBe('');
    avatar.dispatchEvent(new Event('error'));
    expect(avatar.style.display).toBe('none');
  });
});
