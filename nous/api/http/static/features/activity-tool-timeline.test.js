/* =================================================================
   activity.js — tool.called timeline table
   Covers: newest-first ordering, 100-row cap, duration_ms / exit_code /
   command columns from metadata, "—" when metadata lacks them
   (chat registry events carry none), command collapsed to one line.
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore } from '../core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
let A;

beforeAll(() => {
  loadCore();
  // activity.js captures window.S and Nous.Core at load time.
  window.S = { persona: 'p1', tab: 'activity' };
  window.Nous.Core.fmtDateTime = (ts) => String(ts).replace('T', ' ');
  window.Nous.Core.relativeTime = (ts) => String(ts);
  globalThis.N = window.Nous; // script-tag global
  // DOMPurify はブラウザ CDN グローバル。vitest では identity stub（else 経路は textContent）
  globalThis.DOMPurify = { sanitize: (html) => String(html) };
  const code = readFileSync(resolve(__dirname, 'activity.js'), 'utf-8');
  new Function(code)();
  A = window.Nous.Features.Activity;
});

beforeEach(() => {
  document.body.innerHTML = '<div id="act-feed"></div>';
});

it('renders tool.called rows newest first with duration/exit/command and dashes when absent', () => {
  const many = Array.from({ length: 105 }, (_, i) => ({
    timestamp: `2025-12-30T00:00:${String(i % 60).padStart(2, '0')}.${i}`,
    summary: 'filler: ✓',
    metadata: { tool_name: 'filler' },
  }));
  const events = [
    {
      timestamp: '2026-01-01T00:00:01',
      summary: 'shell: ✓',
      metadata: { tool_name: 'shell', duration_ms: 12.5, exit_code: 0, command: 'ls -la /tmp' },
    },
    {
      timestamp: '2026-01-01T00:00:03',
      summary: 'workspace_read: ✗',
      metadata: null, // chat 側 registry 発行分は metadata を持たない
    },
    {
      timestamp: '2026-01-01T00:00:02',
      summary: 'memory_search: ✓',
      metadata: { tool_name: 'memory_search', duration_ms: 40, exit_code: 2, command: 'q\nsecond line' },
    },
    ...many,
  ];

  A.renderToolTimeline(events);

  const rows = [...document.querySelectorAll('#act-feed .act-tool-row')];
  expect(rows).toHaveLength(100); // 上限 100 件

  const head = [...document.querySelectorAll('#act-feed th')].map((th) => th.textContent);
  expect(head).toEqual(['Time', 'Tool', 'Duration', 'Exit', 'Command']);

  // 新しい順（同日時内の 00:00:03 が先頭、次に 00:00:02、00:00:01）
  expect(rows[0].querySelector('.act-tool-name').textContent).toBe('workspace_read');
  expect(rows[1].querySelector('.act-tool-name').textContent).toBe('memory_search');
  expect(rows[2].querySelector('.act-tool-name').textContent).toBe('shell');

  // metadata 欠落時は "—"
  expect(rows[0].querySelector('.act-tool-duration').textContent).toBe('—');
  expect(rows[0].querySelector('.act-tool-exit').textContent).toBe('—');
  expect(rows[0].querySelector('.act-tool-command').textContent).toBe('—');
  expect(rows[0].querySelector('.act-tool-time').textContent).toBe('2026-01-01 00:00:03');

  // metadata あり: 値そのまま + command は 1 行に潰す
  expect(rows[1].querySelector('.act-tool-duration').textContent).toBe('40 ms');
  expect(rows[1].querySelector('.act-tool-exit').textContent).toBe('2');
  expect(rows[1].querySelector('.act-tool-command').textContent).toBe('q');
  expect(rows[2].querySelector('.act-tool-exit').textContent).toBe('0'); // exit 0 は "—" にしない
});
