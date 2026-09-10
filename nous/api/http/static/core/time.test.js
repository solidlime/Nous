import { loadCore } from './load-core.js';

let N;

beforeAll(() => {
  loadCore();
  N = window.Nous.Core;
});

describe('N.Core.relativeTime', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-15T12:00:00.000Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns "--" for null', () => {
    expect(N.relativeTime(null)).toBe('--');
  });

  it('returns "--" for undefined', () => {
    expect(N.relativeTime(undefined)).toBe('--');
  });

  it('returns "--" for empty string', () => {
    expect(N.relativeTime('')).toBe('--');
  });

  it('returns "just now" for future dates', () => {
    expect(N.relativeTime('2026-01-15T12:00:01.000Z')).toBe('just now');
    expect(N.relativeTime('2026-01-16T12:00:00.000Z')).toBe('just now');
  });

  it('returns "Xs ago" for seconds', () => {
    expect(N.relativeTime('2026-01-15T11:59:55.000Z')).toBe('5s ago');
    expect(N.relativeTime('2026-01-15T11:59:30.000Z')).toBe('30s ago');
  });

  it('returns "Xm ago" for minutes', () => {
    expect(N.relativeTime('2026-01-15T11:55:00.000Z')).toBe('5m ago');
    expect(N.relativeTime('2026-01-15T11:30:00.000Z')).toBe('30m ago');
  });

  it('returns "Xh ago" for hours', () => {
    expect(N.relativeTime('2026-01-15T07:00:00.000Z')).toBe('5h ago');
    expect(N.relativeTime('2026-01-14T13:00:00.000Z')).toBe('23h ago');
  });

  it('returns "Xd ago" for days', () => {
    expect(N.relativeTime('2026-01-14T12:00:00.000Z')).toBe('1d ago');
    expect(N.relativeTime('2026-01-08T12:00:00.000Z')).toBe('7d ago');
  });
});

describe('N.Core.fmtDate', () => {
  it('returns "--" for null/undefined/empty string', () => {
    expect(N.fmtDate(null)).toBe('--');
    expect(N.fmtDate(undefined)).toBe('--');
    expect(N.fmtDate('')).toBe('--');
  });

  it('formats a valid date string', () => {
    const result = N.fmtDate('2026-01-15T12:00:00.000Z');
    expect(typeof result).toBe('string');
    expect(result).not.toBe('--');
    expect(result.length).toBeGreaterThan(0);
  });
});

describe('N.Core.fmtDateTime', () => {
  it('returns "--" for null/undefined/empty string', () => {
    expect(N.fmtDateTime(null)).toBe('--');
    expect(N.fmtDateTime(undefined)).toBe('--');
    expect(N.fmtDateTime('')).toBe('--');
  });

  it('formats a full date-time string', () => {
    const result = N.fmtDateTime('2026-01-15T12:00:00.000Z');
    expect(typeof result).toBe('string');
    expect(result).not.toBe('--');
    expect(result.length).toBeGreaterThan(0);
    // full date-time variant: date AND time components present
    expect(result).toMatch(/2026/);
    expect(result).toMatch(/(0?[0-9]|1[0-9]|2[0-3]):[0-5][0-9]/);
  });
});

describe('N.Core.fmtStamp', () => {
  it('returns a fixed-width YYYY/MM/DD HH:MM label (local time)', () => {
    const result = N.fmtStamp('2026-01-15T12:00:00');
    expect(result).toMatch(/^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}$/);
    expect(result).toBe(
      new Date('2026-01-15T12:00:00').getFullYear() + '/01/15 ' +
      String(new Date('2026-01-15T12:00:00').getHours()).padStart(2, '0') + ':' +
      String(new Date('2026-01-15T12:00:00').getMinutes()).padStart(2, '0'),
    );
  });

  it('returns "" (not "--") for empty and unparseable input', () => {
    expect(N.fmtStamp('')).toBe('');
    expect(N.fmtStamp(null)).toBe('');
    expect(N.fmtStamp(undefined)).toBe('');
    expect(N.fmtStamp('now')).toBe('');
  });
});
