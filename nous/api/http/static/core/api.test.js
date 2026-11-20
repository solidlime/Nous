import { loadCore } from './load-core.js';

let N;

beforeAll(() => {
  loadCore();
  N = window.Nous.Core;
});

describe('N.Core.api()', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns JSON for a successful response', async () => {
    const mockData = { ok: true, data: 'hello' };
    fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockData),
    });

    const result = await N.api('/test');
    expect(result).toEqual(mockData);
    // GET carries no body — no Content-Type header
    expect(fetch).toHaveBeenCalledWith('/test', expect.objectContaining({
      headers: {},
    }));
  });

  it('adds Content-Type: application/json to body-carrying (POST) requests', async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    });

    await N.api('/test', { method: 'POST', body: '{}' });
    expect(fetch).toHaveBeenCalledWith('/test', expect.objectContaining({
      headers: { 'Content-Type': 'application/json' },
    }));
  });

  it('throws on non-OK response', async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: () => Promise.resolve({ error: 'Not Found' }),
    });

    await expect(N.api('/missing')).rejects.toThrow('Not Found');
  });

  it('tags the thrown error with the HTTP status', async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      json: () => Promise.resolve({ detail: 'turn already running' }),
    });

    let caught = null;
    try {
      await N.api('/api/chat/p1', { method: 'POST', suppressErrorToast: true });
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeTruthy();
    expect(caught.status).toBe(409);
  });

  it('throws on network error', async () => {
    fetch.mockRejectedValue(new Error('Network failure'));
    await expect(N.api('/fail')).rejects.toThrow('Network failure');
  });

  it('does not fire the global error hook for aborted requests', async () => {
    const onError = vi.fn();
    N.api._onError = onError;
    const abort = new Error('aborted');
    abort.name = 'AbortError';
    fetch.mockRejectedValue(abort);

    await expect(N.api('/slow')).rejects.toThrow('aborted');
    expect(onError).not.toHaveBeenCalled();
    N.api._onError = null;
  });

  it('suppresses the global error hook when suppressErrorToast is set', async () => {
    const onError = vi.fn();
    N.api._onError = onError;
    fetch.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: () => Promise.resolve({ error: 'Memory not found: opencode.json' }),
    });

    await expect(N.api('/missing', { suppressErrorToast: true })).rejects.toThrow(
      'Memory not found: opencode.json',
    );
    expect(onError).not.toHaveBeenCalled();
    N.api._onError = null;
  });

  it('sends custom headers when provided', async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });

    await N.api('/test', { headers: { Authorization: 'Bearer token' } });
    expect(fetch).toHaveBeenCalledWith('/test', expect.objectContaining({
      headers: {
        Authorization: 'Bearer token',
      },
    }));
  });
});

/* =================================================================
   #106: rawFetch is the thin surface for calls api() cannot serve —
   streaming bodies (TTS), FormData uploads, non-JSON responses.
   It must NOT add api()'s error policy: no implicit timeout, no ok
   check, no JSON parsing. Its only job is the Content-Type rule and
   single-source fetch access (auth wrap / future cookie migration).
   ================================================================= */
describe('N.Core.api.rawFetch()', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns the raw Response without an ok check or JSON parsing', async () => {
    const raw = { ok: false, status: 404 };
    fetch.mockResolvedValue(raw);

    const result = await N.api.rawFetch('/missing', { method: 'DELETE' });
    expect(result).toBe(raw);
    expect(fetch).toHaveBeenCalledWith('/missing', expect.objectContaining({
      method: 'DELETE',
    }));
  });

  it('injects Content-Type: application/json for body-carrying POSTs', async () => {
    fetch.mockResolvedValue({ ok: true });

    await N.api.rawFetch('/tts/x/stream', { method: 'POST', body: '{}' });
    expect(fetch).toHaveBeenCalledWith('/tts/x/stream', expect.objectContaining({
      headers: { 'Content-Type': 'application/json' },
    }));
  });

  it('never sets Content-Type on FormData (browser owns the multipart boundary)', async () => {
    fetch.mockResolvedValue({ ok: true });
    const fd = new FormData();
    fd.append('file', 'x');

    await N.api.rawFetch('/api/chat/p/attachment/upload', { method: 'POST', body: fd });
    expect(fetch).toHaveBeenCalledWith('/api/chat/p/attachment/upload', expect.objectContaining({
      headers: {},
    }));
  });

  it('passes the caller signal through with no implicit timeout', async () => {
    fetch.mockResolvedValue({ ok: true });
    const ctrl = new AbortController();

    await N.api.rawFetch('/tts/x/stream', { method: 'POST', body: '{}', signal: ctrl.signal });
    expect(fetch).toHaveBeenCalledWith('/tts/x/stream', expect.objectContaining({
      signal: ctrl.signal,
    }));
  });

  it('keeps custom headers untouched (no double trace of a default timeout object)', async () => {
    fetch.mockResolvedValue({ ok: true });

    await N.api.rawFetch('/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    expect(fetch).toHaveBeenCalledWith('/test', expect.objectContaining({
      headers: { 'Content-Type': 'application/json' },
    }));
  });
});
