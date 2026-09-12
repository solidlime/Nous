/* =================================================================
   help-tooltip regression — consecutive hover must not stack popups.
   The old _hideTooltip queried the first .chat-help-tooltip in DOM
   order, so a stale mid-fade tooltip could be hidden instead of the
   live one, leaving the visible popup stuck on screen.
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore } from '../core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

beforeAll(() => {
  loadCore();
  window.S = { persona: 'p1' };
  window.Nous.Core.toast = window.Nous.Core.toast || (() => {});
  const code = readFileSync(resolve(__dirname, 'chat-core.js'), 'utf-8');
  new Function(code)();
});

beforeEach(() => {
  document.querySelectorAll('.chat-help-tooltip').forEach((t) => t.remove());
  document.body.innerHTML =
    '<span class="chat-help-icon" data-category="core" id="h1"></span>' +
    '<span class="chat-help-icon" data-category="context" id="h2"></span>' +
    '<span class="chat-help-icon" data-category="voice" id="h3"></span>';
});

const show = (id) => window.Nous.Chat.core.showHelp(document.getElementById(id));
const hide = () => window.Nous.Chat.core.hideHelp();

describe('help tooltip lifecycle', () => {
  it('reuses a single tooltip node across consecutive hovers', () => {
    show('h1');
    show('h2');
    show('h3');
    expect(document.querySelectorAll('.chat-help-tooltip').length).toBe(1);
    expect(document.querySelector('.chat-help-tooltip').textContent).toContain('音声');
  });

  it('hides the live tooltip and leaves nothing stuck after rapid hover', async () => {
    show('h1');
    show('h2');
    hide();
    await new Promise((r) => setTimeout(r, 250));
    expect(document.querySelectorAll('.chat-help-tooltip').length).toBe(0);
  });

  it('never ends with more than one tooltip even without hiding', () => {
    for (let i = 0; i < 10; i++) {
      show(i % 2 ? 'h2' : 'h1');
    }
    expect(document.querySelectorAll('.chat-help-tooltip').length).toBe(1);
  });
});
