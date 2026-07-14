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
