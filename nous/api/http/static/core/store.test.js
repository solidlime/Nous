import { loadCore, loadStore } from './load-core.js';

let N;

beforeAll(() => {
  loadCore();
  N = window.Nous.Core;
});

beforeEach(() => {
  loadStore();  // fresh _state / _listeners for each test
});

describe('N.Core.store.init()', () => {
  it('initializes with defaults', () => {
    N.store.init({ a: 1, b: 2 });
    expect(N.store.get('a')).toBe(1);
    expect(N.store.get('b')).toBe(2);
  });

  it('does not overwrite existing values', () => {
    N.store.set('x', 42);
    N.store.init({ x: 99, y: 10 });
    expect(N.store.get('x')).toBe(42);
    expect(N.store.get('y')).toBe(10);
  });
});

describe('N.Core.store.set() / get()', () => {
  it('set() updates a value and get() retrieves it', () => {
    N.store.set('name', 'Nous');
    expect(N.store.get('name')).toBe('Nous');
  });

  it('get() returns undefined for unset keys', () => {
    expect(N.store.get('nonexistent')).toBeUndefined();
  });

  it('set() overwrites existing values', () => {
    N.store.set('key', 'first');
    N.store.set('key', 'second');
    expect(N.store.get('key')).toBe('second');
  });
});

describe('N.Core.store.on()', () => {
  it('subscribes to changes for a specific key', () => {
    const fn = vi.fn();
    N.store.on('foo', fn);
    N.store.set('foo', 'bar');
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn).toHaveBeenCalledWith('bar', undefined);
  });

  it('notifies with old value on update', () => {
    const fn = vi.fn();
    N.store.set('counter', 1);
    N.store.on('counter', fn);
    N.store.set('counter', 2);
    expect(fn).toHaveBeenCalledWith(2, 1);
  });

  it('unsubscribes when the returned function is called', () => {
    const fn = vi.fn();
    const unsub = N.store.on('foo', fn);
    unsub();
    N.store.set('foo', 'bar');
    expect(fn).not.toHaveBeenCalled();
  });

  it('on("*") catches all changes', () => {
    const fn = vi.fn();
    N.store.on('*', fn);
    N.store.set('a', 1);
    N.store.set('b', 2);
    expect(fn).toHaveBeenCalledTimes(2);
    expect(fn).toHaveBeenCalledWith('a', 1, undefined);
    expect(fn).toHaveBeenCalledWith('b', 2, undefined);
  });

  it('multiple listeners for the same key', () => {
    const fn1 = vi.fn();
    const fn2 = vi.fn();
    N.store.on('key', fn1);
    N.store.on('key', fn2);
    N.store.set('key', 'val');
    expect(fn1).toHaveBeenCalledTimes(1);
    expect(fn2).toHaveBeenCalledTimes(1);
  });
});

describe('N.Core.store.dump()', () => {
  it('returns a full state snapshot', () => {
    N.store.set('x', { nested: true });
    const snap = N.store.dump();
    expect(snap).toEqual({ x: { nested: true } });
  });

  it('returns a clone not a reference', () => {
    N.store.set('y', [1, 2, 3]);
    const snap = N.store.dump();
    snap.y.push(4);
    expect(N.store.get('y')).toEqual([1, 2, 3]);
  });
});
