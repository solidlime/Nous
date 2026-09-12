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
        'Content-Type': 'application/json',
        Authorization: 'Bearer token',
      },
    }));
  });
});
