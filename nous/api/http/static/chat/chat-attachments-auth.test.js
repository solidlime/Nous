/* =================================================================
   #102 — img/audio の src URL に資格情報が乗ること（openViewer 入口の sign）。
   auth.test.js が sign() 単体を担保するので、ここは src への投入を証明する。
   ================================================================= */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

async function load() {
  window.Nous = window.Nous || {};
  window.Nous.Core = window.Nous.Core || {};
  window.Nous.Core.esc = (s) => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
  window.Nous.Core.safeSetHTML = (el, html) => { el.innerHTML = html; };
  window.Nous.Core.auth = {
    sign: (u) => (u && u.indexOf('?') === -1 ? u + '?token=k' : u),
  };
  window.Nous.Chat = window.Nous.Chat || {};
  window.Nous.Chat.state = window.Nous.Chat.state || {};
  window.S = window.S || {};
  // viewer overlay/inner の DOM — openMediaViewer が必須とする要素
  overlay = document.createElement('div');
  overlay.id = 'media-viewer-overlay';
  inner = document.createElement('div');
  inner.id = 'media-viewer-inner';
  overlay.appendChild(inner);
  document.body.appendChild(overlay);
  await import(/* @vite-ignore */ `../chat/chat-attachments.js?t=${Math.random()}`);
  return window.Nous.Chat.attachments;
}

let overlay, inner;

describe('#102 media src auth (chat-attachments)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  afterEach(() => {
    document.body.innerHTML = '';
    delete window.Nous;
  });

  it('openViewer は img src に ?token= を載せる', async () => {
    const attachments = await load();
    attachments.openViewer('/api/chat/herta/attachment/a.png', 'image');
    const img = inner.querySelector('img');
    expect(img).toBeTruthy();
    expect(img.src).toContain('/api/chat/herta/attachment/a.png?token=k');
  });

  it('openViewer は audio の <source src> に ?token= を載せる', async () => {
    const attachments = await load();
    attachments.openViewer('/api/tts/herta/cache/x.wav', 'audio', 'audio/wav');
    const source = inner.querySelector('source');
    expect(source).toBeTruthy();
    expect(source.src).toContain('/api/tts/herta/cache/x.wav?token=k');
  });

  it('openViewer は pdf を iframe でなく新タブで開く（XFO DENY 対策）', async () => {
    const attachments = await load();
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    attachments.openViewer('/api/chat/herta/attachment/doc.pdf', 'pdf');
    expect(openSpy).toHaveBeenCalledWith(
      '/api/chat/herta/attachment/doc.pdf?token=k', '_blank', 'noopener');
    // iframe は描画されないので DOM には置かない
    expect(inner.querySelector('iframe')).toBe(null);
    openSpy.mockRestore();
  });

  it('openViewer は外部 URL の pdf は開かない（open redirect 防護）', async () => {
    const attachments = await load();
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    attachments.openViewer('https://evil.example/doc.pdf', 'pdf');
    expect(openSpy).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it('viewer を閉じたら inner は空になる', async () => {
    const attachments = await load();
    attachments.openViewer('/api/chat/herta/attachment/a.png', 'image');
    attachments.closeViewer();
    expect(inner.textContent).toBe('');
  });

  it('viewer を閉じたら audio は pause される（要素を外しても鳴り続けるため）', async () => {
    const attachments = await load();
    attachments.openViewer('/api/tts/herta/cache/x.wav', 'audio', 'audio/wav');
    const audio = inner.querySelector('audio');
    expect(audio).toBeTruthy();
    const pauseSpy = vi.spyOn(audio, 'pause');
    attachments.closeViewer();
    expect(pauseSpy).toHaveBeenCalled();
    expect(inner.textContent).toBe('');
  });

  it('open し直すとき前回の audio は pause される', async () => {
    const attachments = await load();
    attachments.openViewer('/api/tts/herta/cache/x.wav', 'audio', 'audio/wav');
    const first = inner.querySelector('audio');
    const pauseSpy = vi.spyOn(first, 'pause');
    attachments.openViewer('/api/chat/herta/attachment/a.png', 'image');
    expect(pauseSpy).toHaveBeenCalled();
  });
});
