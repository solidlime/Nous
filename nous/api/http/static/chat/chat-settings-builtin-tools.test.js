/* =================================================================
   chat settings — 組み込みツールのオンオフ checkbox
   Covers: MEMORY_TOOLS 相当の静的リスト描画、disabled_tools の反映、
   チェック操作が state と save に届くこと。
   ================================================================= */
import { loadCore, loadFile } from '../core/load-core.js';

let N;
let saves;

beforeAll(() => {
  loadCore();
  globalThis.DOMPurify = { sanitize: (html) => String(html) };
  N = window.Nous;
  N.Chat = N.Chat || {};
  N.Chat.state = {};
  N.Chat.settings = { save: () => { saves += 1; } };
  window.S = { persona: 'p1' };
  loadFile('../chat/chat-settings-mcp.js');
});

beforeEach(() => {
  saves = 0;
  document.body.innerHTML = '<div id="chat-builtin-tools-list"></div>';
  N.Chat.state.disabledTools = new Set(['memory_search']);
});

describe('N.Chat.settings.renderBuiltinTools', () => {
  it('renders one checkbox per built-in tool, disabled ones unchecked', () => {
    N.Chat.settings.renderBuiltinTools();
    const boxes = document.querySelectorAll('#chat-builtin-tools-list input[type=checkbox]');
    expect(boxes.length).toBe(N.Chat.settings.BUILTIN_TOOLS.length);
    const byName = {};
    boxes.forEach((cb) => { byName[cb.id] = cb; });
    expect(byName['builtin-tool-cb-memory_create'].checked).toBe(true);
    expect(byName['builtin-tool-cb-memory_search'].checked).toBe(false);
  });

  it('writes the checkbox state into disabledTools and saves', () => {
    N.Chat.settings.renderBuiltinTools();
    const create = document.getElementById('builtin-tool-cb-memory_create');
    create.checked = false;
    create.dispatchEvent(new window.Event('change'));
    expect(N.Chat.state.disabledTools.has('memory_create')).toBe(true);

    const search = document.getElementById('builtin-tool-cb-memory_search');
    search.checked = true;
    search.dispatchEvent(new window.Event('change'));
    expect(N.Chat.state.disabledTools.has('memory_search')).toBe(false);
    expect(saves).toBe(2);
  });

  it('does nothing when the container is absent', () => {
    document.body.innerHTML = '';
    expect(() => N.Chat.settings.renderBuiltinTools()).not.toThrow();
  });
});
