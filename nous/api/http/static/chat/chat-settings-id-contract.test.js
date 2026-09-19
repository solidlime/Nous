/* =================================================================
   settings ID contract test — 4重手書き対応表の機械検証
   Cross-checks (statically, no browser):
     1. RESET_FIELDS in chat-settings.js (id -> config-key bindings)
     2. applyChatConfig / saveChatConfig getElementById("chat-...") ids
     3. radio `name=` selectors used by chat-settings.js
   against the input ids / radio names that the Python side
   (nous/api/http/sections/chat/*.py) renders into the settings HTML.
   A mismatch here silently breaks load/save/reset for that field.
   ================================================================= */
import { readFileSync, readdirSync } from 'fs';
import { resolve, dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = resolve(__dirname, '..');
// sections/ sits next to static/ under nous/api/http/
const SECTIONS_DIR = resolve(STATIC_DIR, '../sections/chat');

// chat-settings.js split into settings/*.js — the contract test reads the
// concatenated chunk sources (reader path only; logic unchanged).
const settingsSrc = ['settings/reset.js', 'settings/apply.js', 'settings/apply-groups.js', 'settings/save.js']
  .map((f) => readFileSync(resolve(__dirname, f), 'utf-8'))
  .join('\n');

function collectPythonAttrs() {
  const ids = new Set();
  const names = new Set();
  for (const f of readdirSync(SECTIONS_DIR)) {
    if (!f.endsWith('.py')) continue;
    const src = readFileSync(join(SECTIONS_DIR, f), 'utf-8');
    for (const m of src.matchAll(/id="([^"]+)"/g)) ids.add(m[1]);
    for (const m of src.matchAll(/name="([^"]+)"/g)) names.add(m[1]);
  }
  return { ids, names };
}

// Parse RESET_FIELDS entries: [..., "chat-id", "config_key", kind?, extra?]
// Entries may span multiple lines; each entry has no nested brackets.
function resetFieldEntries() {
  const start = settingsSrc.indexOf('var RESET_FIELDS = [');
  if (start < 0) throw new Error('RESET_FIELDS not found in chat-settings.js');
  const end = settingsSrc.indexOf('\n  ];', start);
  if (end < 0) throw new Error('RESET_FIELDS closing bracket not found');
  const block = settingsSrc.slice(start, end);
  return [...block.matchAll(/\[([^[\]]*)\]/g)].map((m) =>
    [...m[1].matchAll(/"([^"]*)"/g)].map((s) => s[1]),
  );
}

describe('chat settings ID contract (JS ↔ Python sections)', () => {
  const py = collectPythonAttrs();
  const entries = resetFieldEntries();

  it('parses a non-empty RESET_FIELDS table', () => {
    expect(entries.length).toBeGreaterThan(80);
  });

  it('every RESET_FIELDS element id exists in the Python-rendered section HTML', () => {
    const missing = [];
    for (const e of entries) {
      const id = e[0];
      if (e[2] === 'radio') continue; // checked via name= in the next test
      if (!py.ids.has(id)) missing.push(id);
    }
    expect(missing).toEqual([]);
  });

  it('every RESET_FIELDS radio name has matching radio inputs in Python HTML', () => {
    const missing = [];
    for (const e of entries) {
      if (e[2] === 'radio' && !py.names.has(e[0])) missing.push(e[0]);
    }
    expect(missing).toEqual([]);
  });

  it('every RESET_FIELDS "optional" checkbox id exists in the Python HTML', () => {
    const missing = [];
    for (const e of entries) {
      if (e[2] === 'optional' && e[3] && !py.ids.has(e[3])) missing.push(e[3]);
    }
    expect(missing).toEqual([]);
  });

  it('every getElementById("chat-...") in chat-settings.js exists in the Python HTML', () => {
    const missing = [];
    const seen = new Set();
    for (const m of settingsSrc.matchAll(/getElementById\(\s*"([^"]+)"/g)) {
      const id = m[1];
      if (!id.startsWith('chat-') || seen.has(id)) continue;
      seen.add(id);
      // dynamic preset lookup: "chat-image-gen-preset-" + name (full ids come
      // from RESET_FIELDS, already covered above)
      if (id.endsWith('-')) continue;
      if (!py.ids.has(id)) missing.push(id);
    }
    expect(missing).toEqual([]);
  });
});
