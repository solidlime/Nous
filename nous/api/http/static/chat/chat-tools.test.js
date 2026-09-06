/* =================================================================
   chat-tools tests — immersive tool chips
   Covers: narrative labels (no raw tool names), icon mapping,
   running state without duplicate status text, done check,
   debug details preserved, unknown-tool fallback.
   ================================================================= */
import { loadCore, loadFile } from '../core/load-core.js';

let N;

beforeAll(() => {
  loadCore();
  globalThis.DOMPurify = { sanitize: (html) => String(html) };
  // jsdom (vitest env) lacks the CSS global — browser has it natively.
  globalThis.CSS = { escape: (s) => String(s) };
  N = window.Nous;
  window.S = { persona: 'p1' };
  // chat-tools reads these at load time
  N.Chat = N.Chat || {};
  N.Chat.state = {};
  N.Chat.ui = {};
  loadFile('../chat/chat-tools.js');
});

beforeEach(() => {
  document.body.innerHTML = '<div id="chat-messages"></div>';
});

describe('N.Chat.tools — labels', () => {
  it('maps known tools to persona-neutral narration', () => {
    expect(N.Chat.tools.label('memory_create')).toBe('思い出を刻んでる…');
    expect(N.Chat.tools.label('invoke_skill')).toBe('技を繰り出す準備…');
  });

  it('shows raw names for non-nous tools (skills, MCP)', () => {
    // スキル名は没入ラベル化しない（ユーザー指示: recall_weaver は生名のまま）
    expect(N.Chat.tools.label('recall_weaver')).toBe('recall_weaver');
    expect(N.Chat.tools.label('weird_mcp_tool_xyz')).toBe('weird_mcp_tool_xyz');
  });
});

describe('N.Chat.tools — icons', () => {
  it('uses sparkles for skill-like tools, wrench for generic ones', () => {
    expect(N.Chat.tools.icon('invoke_skill')).toBe('sparkles');
    expect(N.Chat.tools.icon('list_skills')).toBe('sparkles');
    expect(N.Chat.tools.icon('image_generate')).toBe('image');
    expect(N.Chat.tools.icon('memory_search')).toBe('brain');
    expect(N.Chat.tools.icon('bash')).toBe('wrench');
  });
});

describe('N.Chat.tools — chip markup', () => {
  it('renders an immersive running chip with debug details preserved', () => {
    const div = N.Chat.tools.append('tool_call', {
      id: 't1',
      name: 'list_skills',
      input: { category: 'all' },
    });
    expect(div.className).toBe('chat-tool-call');
    expect(div.dataset.toolId).toBe('t1');
    const strong = div.querySelector('strong');
    expect(strong.textContent).toBe('使える技を確認してる…');
    expect(strong.getAttribute('title')).toBe('list_skills'); // raw name kept for debug
    expect(div.querySelector('.chat-tool-summary-left i').getAttribute('data-lucide')).toBe('sparkles');
    // running state: no duplicate status text; slot hidden via :empty
    const status = div.querySelector('.chat-tool-status');
    expect(status.textContent.trim()).toBe('');
    // debug expansion intact
    expect(div.querySelector('pre.chat-tool-detail').textContent).toContain('"category": "all"');
    expect(div.querySelector('.chat-tool-chevron')).not.toBeNull();
  });

  it('marks the chip done with a subtle check and appends the result pre', () => {
    N.Chat.tools.append('tool_call', { id: 't2', name: 'memory_search', input: {} });
    N.Chat.tools.append('tool_result', { id: 't2', name: 'memory_search', result: { hits: 3 } });
    const callDiv = document.querySelector('[data-tool-id="t2"]');
    expect(callDiv.classList.contains('done')).toBe(true);
    expect(callDiv.querySelector('.chat-tool-status').innerHTML).toContain('check');
    expect(callDiv.querySelector('.chat-tool-result-content').textContent).toContain('hits');
  });
});
