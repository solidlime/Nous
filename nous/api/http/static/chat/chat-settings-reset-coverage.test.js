/* =================================================================
   reset coverage test — save.js の設定キー集合 ⊆ reset.js の対応集合
   Audit L5: saveChatConfig が収集する config キーに「デフォルトに戻す」
   バインディングが無いと、そのフィールドだけリセットできない（静かな
   取りこぼし）。ここでは両ファイルを静的に読み、差分を機械的に検証する。
   非リセット対象は下の明示リストにだけ置き、リストが黙って増えないよう
   件数と所属も固定する。
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

const read = (f) => readFileSync(resolve(__dirname, f), 'utf-8');
const resetSrc = read('settings/reset.js');
const saveSrc = read('settings/save.js');

// Payload items that are NOT config keys (api() call options, not the config
// body). They never show up in the payload literal parsed below.
const NON_SETTING_PAYLOAD_KEYS = ['method', 'body'];

// Config keys with no per-field reset binding:
//  - enabled_skills / disabled_tools: set-valued, edited through the skills
//    and tools pickers (no single value control to reset)
//  - voice_emotion_link / irodori_caption_llm_enabled: legacy bool aliases
//    derived from the chat-voice-emotion-mode radio (already reset by it)
// Note: mcp_servers (json) and image_gen_presets (preset entries) ARE config
// keys and do have reset bindings — no exclusion needed for them.
const NOT_RESETTABLE = [
  'enabled_skills',
  'disabled_tools',
  'voice_emotion_link',
  'irodori_caption_llm_enabled',
];

// Top-level keys of the `const payload = { ... }` literal.
function savePayloadKeys() {
  const start = saveSrc.indexOf('const payload = {');
  if (start < 0) throw new Error('payload literal not found in save.js');
  const end = saveSrc.indexOf('\n    };', start);
  if (end < 0) throw new Error('payload literal end not found in save.js');
  const body = saveSrc.slice(start, end);
  const keys = [...body.matchAll(/^\s{6}([a-z_][a-z0-9_]*):/gm)].map((m) => m[1]);
  // conditional additions assigned after the literal (brain_llm_*)
  for (const m of saveSrc.matchAll(/payload\.([a-z_][a-z0-9_]*)\s*=/g)) keys.push(m[1]);
  return [...new Set(keys)];
}

// RESET_FIELDS entries: [..., "chat-id", "config_key", kind?, extra?]
function resetKeys() {
  const start = resetSrc.indexOf('var RESET_FIELDS = [');
  if (start < 0) throw new Error('RESET_FIELDS not found in reset.js');
  const end = resetSrc.indexOf('\n  ];', start);
  if (end < 0) throw new Error('RESET_FIELDS closing bracket not found');
  const block = resetSrc.slice(start, end);
  const entries = [...block.matchAll(/\[([^[\]]*)\]/g)].map((m) =>
    [...m[1].matchAll(/"([^"]*)"/g)].map((s) => s[1]),
  );
  return { entries, keys: new Set(entries.map((e) => e[1])) };
}

describe('reset coverage (save.js keys ⊆ RESET_FIELDS keys)', () => {
  const saveKeys = savePayloadKeys();
  const { entries, keys: resetKeySet } = resetKeys();

  it('parses both tables', () => {
    expect(saveKeys.length).toBeGreaterThan(100);
    expect(entries.length).toBeGreaterThan(80);
  });

  it('every config key collected by saveChatConfig has a reset binding', () => {
    const missing = saveKeys.filter(
      (k) =>
        !resetKeySet.has(k) &&
        !NOT_RESETTABLE.includes(k) &&
        !NON_SETTING_PAYLOAD_KEYS.includes(k),
    );
    expect(missing).toEqual([]);
  });

  it('documents the exclusion lists (they must not silently grow)', () => {
    expect([...NOT_RESETTABLE].sort()).toEqual([
      'disabled_tools',
      'enabled_skills',
      'irodori_caption_llm_enabled',
      'voice_emotion_link',
    ]);
    for (const k of NOT_RESETTABLE) {
      expect(resetKeySet.has(k)).toBe(false); // really unbound
      expect(saveKeys).toContain(k); // really collected by save.js
    }
    expect(NON_SETTING_PAYLOAD_KEYS).toEqual(['method', 'body']);
    for (const k of NON_SETTING_PAYLOAD_KEYS) {
      expect(resetKeySet.has(k)).toBe(false);
      expect(saveKeys).not.toContain(k); // api() options, not payload keys
    }
  });
});
