/* =================================================================
   Blob URL lifecycle (#122): every URL.createObjectURL'd chunk must be
   revoked at least once — on natural end (onended), on element error, on
   play() rejection or synchronous throw, and on T.stop (queued URLs +
   the playing audio's src). A late handler
   on a superseded element may revoke the same URL twice; that is
   harmless (revoke is idempotent) and allowed. Long sessions otherwise
   accumulate blob: URLs (memory leak flagged in #120 review).
   ================================================================= */
import { describe, it, expect, beforeEach, afterEach, beforeAll } from 'vitest';
import { loadCore, loadFile } from '../core/load-core.js';

const created = [];
const revoked = [];
let seq = 0;

beforeAll(() => {
  loadCore();
});

beforeEach(() => {
  created.length = 0;
  revoked.length = 0;
  seq = 0;
  window.Nous.Chat = window.Nous.Chat || {};
  // jsdom has no URL.createObjectURL/revokeObjectURL — inject counting stubs.
  URL.createObjectURL = () => {
    const u = 'blob:fake-' + ++seq;
    created.push(u);
    return u;
  };
  URL.revokeObjectURL = (u) => {
    revoked.push(u);
  };
  loadFile('../chat/chat-tts-stream.js');
});

afterEach(() => {
  delete URL.createObjectURL;
  delete URL.revokeObjectURL;
  delete window.Nous.Chat.ttsStream;
});

describe('TTS stream Blob URL lifecycle (#122)', () => {
  it('T.stop revokes queued URLs and the playing audio URL', () => {
    const T = window.Nous.Chat.ttsStream;
    const stream = T.startStream('p');
    stream.queue.push('blob:q-1', 'blob:q-2');
    stream.audio = { pause: () => {}, src: 'blob:playing-1' };
    T.stop();
    expect(revoked).toEqual(['blob:q-1', 'blob:q-2', 'blob:playing-1']);
    expect(stream.queue).toEqual([]);
    expect(stream.audio).toBe(null);
    expect(stream.stopped).toBe(true);
    expect(stream.playing).toBe(false); // stopped stream never claims to play
  });

  it('T.stop is safe with an empty queue and no audio', () => {
    const T = window.Nous.Chat.ttsStream;
    T.startStream('p');
    expect(() => T.stop()).not.toThrow();
    expect(revoked).toEqual([]);
  });

  it('onended revokes the finished chunk URL before advancing', async () => {
    // One tts_chunk over a fake SSE body, then done.
    const enc = new TextEncoder();
    const chunkLine = enc.encode('data: {"type":"tts_chunk","audio_base64":"AAAA"}\n\n');
    let sent = false;
    const reader = {
      read: () =>
        sent
          ? Promise.resolve({ done: true })
          : ((sent = true), Promise.resolve({ done: false, value: chunkLine })),
    };
    const orig = window.Nous.Core.api.rawFetch;
    window.Nous.Core.api.rawFetch = () =>
      Promise.resolve({ ok: true, body: { getReader: () => reader } });
    let audio1;
    const origAudio = window.Audio;
    window.Audio = function FakeAudio(src) {
      this.src = src;
      audio1 = this;
    };
    window.Audio.prototype.play = function () {
      return Promise.resolve();
    };
    try {
      const T = window.Nous.Chat.ttsStream;
      const stream = T.startStream('p');
      const p = T.finish('こんにちは', null);
      await p;
      expect(audio1).toBeTruthy();
      expect(created.length).toBe(1);
      expect(revoked).toEqual([]); // not revoked while playing
      audio1.onended();
      expect(revoked).toEqual([created[0]]);
      expect(stream.audio).toBe(null);
      expect(stream.playing).toBe(false);
    } finally {
      window.Audio = origAudio;
      window.Nous.Core.api.rawFetch = orig;
    }
  });

  it('a late onerror on a superseded audio revokes it but never kills the next chunk', async () => {
    // Two tts_chunks; the first play() rejects (autoplay blocked), the second plays.
    // The superseded element's late onerror must not clear the newer element.
    const enc = new TextEncoder();
    const lines = [
      enc.encode('data: {"type":"tts_chunk","audio_base64":"AAAA"}\n\n'),
      enc.encode('data: {"type":"tts_chunk","audio_base64":"BBBB"}\n\n'),
    ];
    let i = 0;
    const reader = {
      read: () =>
        i < lines.length
          ? Promise.resolve({ done: false, value: lines[i++] })
          : Promise.resolve({ done: true }),
    };
    const orig = window.Nous.Core.api.rawFetch;
    window.Nous.Core.api.rawFetch = () =>
      Promise.resolve({ ok: true, body: { getReader: () => reader } });
    const audios = [];
    const pauses = [];
    const origAudio = window.Audio;
    window.Audio = function FakeAudio(src) {
      this.src = src;
      audios.push(this);
    };
    window.Audio.prototype.play = function () {
      // First element fails synchronously-rejected; later ones play.
      return audios[0] === this
        ? Promise.reject(new Error('autoplay blocked'))
        : Promise.resolve();
    };
    window.Audio.prototype.pause = function () {
      pauses.push(this.src);
    };
    try {
      const T = window.Nous.Chat.ttsStream;
      const stream = T.startStream('p');
      const p = T.finish('こんにちは', null);
      await p;
      for (let k = 0; k < 50 && audios.length < 2; k++) {
        await new Promise((r) => setTimeout(r, 1));
      }
      expect(audios.length).toBe(2); // rejection advanced to the second chunk
      const [a1, a2] = audios;
      a1.onerror(); // late error from the superseded element
      expect(revoked).toContain(a1.src); // its own URL was revoked (a harmless double revoke is allowed)
      expect(revoked).not.toContain(a2.src); // the live element's URL is untouched
      expect(stream.audio).toBe(a2); // …but the newer element survived
      expect(stream.playing).toBe(true);
      T.stop();
      expect(pauses).toEqual([a2.src]); // stop can still pause the live element
      expect(revoked).toContain(a2.src);
      expect(stream.audio).toBe(null);
    } finally {
      window.Audio = origAudio;
      window.Nous.Core.api.rawFetch = orig;
    }
  });

  it('T.stop still revokes when audio.pause() throws, with an absolute blob URL', () => {
    const T = window.Nous.Chat.ttsStream;
    const stream = T.startStream('p');
    stream.audio = {
      pause: () => {
        throw new Error('already stopped');
      },
      src: 'blob:http://localhost:8789/abc',
    };
    expect(() => T.stop()).not.toThrow();
    expect(revoked).toEqual(['blob:http://localhost:8789/abc']);
    expect(stream.audio).toBe(null);
  });

  it('every created chunk URL is revoked once the turn is stopped (synchronous-throw path)', async () => {
    // play() throws synchronously — the one settle path not covered above.
    // Aggregate invariant: after T.stop, no created URL may remain un-revoked.
    const enc = new TextEncoder();
    const lines = [
      enc.encode('data: {"type":"tts_chunk","audio_base64":"AAAA"}\n\n'),
      enc.encode('data: {"type":"tts_chunk","audio_base64":"BBBB"}\n\n'),
    ];
    let i = 0;
    const reader = {
      read: () =>
        i < lines.length
          ? Promise.resolve({ done: false, value: lines[i++] })
          : Promise.resolve({ done: true }),
    };
    const orig = window.Nous.Core.api.rawFetch;
    window.Nous.Core.api.rawFetch = () =>
      Promise.resolve({ ok: true, body: { getReader: () => reader } });
    const origAudio = window.Audio;
    window.Audio = function FakeAudio(src) {
      this.src = src;
    };
    window.Audio.prototype.play = function () {
      throw new Error('blocked'); // synchronous throw settle path
    };
    try {
      const T = window.Nous.Chat.ttsStream;
      const stream = T.startStream('p');
      await T.finish('こんにちは', null);
      expect(created.length).toBe(2);
      expect(created.every((u) => revoked.includes(u))).toBe(true);
      T.stop();
      expect(created.every((u) => revoked.includes(u))).toBe(true);
      expect(stream.playing).toBe(false);
    } finally {
      window.Audio = origAudio;
      window.Nous.Core.api.rawFetch = orig;
    }
  });
});
