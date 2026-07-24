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

describe('N.Core.store.syncFrom()', () => {
  it('wires an object so writes propagate to store', () => {
    const obj = { a: 1, b: 'hello' };
    N.store.syncFrom(obj);
    obj.a = 42;
    obj.b = 'world';
    expect(N.store.get('a')).toBe(42);
    expect(N.store.get('b')).toBe('world');
  });

  it('wires an object so reads come from store', () => {
    N.store.set('x', 'stored_value');
    const obj = { x: 'initial', y: 3 };
    N.store.syncFrom(obj);
    expect(obj.x).toBe('stored_value');
    expect(obj.y).toBe(3);
  });

  it('does not overwrite existing store values', () => {
    N.store.set('key', 'existing');
    const obj = { key: 'new_value' };
    N.store.syncFrom(obj);
    expect(N.store.get('key')).toBe('existing');
    expect(obj.key).toBe('existing');
  });

  it('notifies listeners when synced property is set', () => {
    const fn = vi.fn();
    N.store.on('foo', fn);
    const obj = { foo: 1 };
    N.store.syncFrom(obj);
    obj.foo = 99;
    expect(fn).toHaveBeenCalledWith(99, 1);
  });

  it('skips function properties', () => {
    const obj = { x: 1, fn: function() { return 42; } };
    N.store.syncFrom(obj);
    expect(typeof obj.fn).toBe('function');
    expect(obj.fn()).toBe(42);
    obj.x = 5;
    expect(N.store.get('x')).toBe(5);
  });

  it('skips non-configurable properties', () => {
    const obj = {};
    Object.defineProperty(obj, 'fixed', { value: 99, configurable: false, enumerable: true });
    Object.defineProperty(obj, 'normal', { value: 1, configurable: true, enumerable: true });
    N.store.syncFrom(obj);
    expect(obj.fixed).toBe(99);
    obj.normal = 42;
    expect(N.store.get('normal')).toBe(42);
  });

  it('uses prefix when provided', () => {
    const obj = { a: 1, b: 2 };
    N.store.syncFrom(obj, 'ns');
    expect(N.store.get('ns.a')).toBe(1);
    expect(N.store.get('ns.b')).toBe(2);
    obj.a = 99;
    expect(N.store.get('ns.a')).toBe(99);
  });
});

describe('N.Core.store.set() — edge cases', () => {
  it('notifies on multiple rapid set() calls', () => {
    const fn = vi.fn();
    N.store.on('key', fn);
    N.store.set('key', 1);
    N.store.set('key', 2);
    N.store.set('key', 3);
    expect(fn).toHaveBeenCalledTimes(3);
    expect(fn).toHaveBeenCalledWith(1, undefined);
    expect(fn).toHaveBeenCalledWith(2, 1);
    expect(fn).toHaveBeenCalledWith(3, 2);
  });

  it('notifies even when setting the same value', () => {
    const fn = vi.fn();
    N.store.set('key', 42);
    N.store.on('key', fn);
    N.store.set('key', 42);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn).toHaveBeenCalledWith(42, 42);
  });

  it('set() with null value', () => {
    N.store.set('key', null);
    expect(N.store.get('key')).toBeNull();
  });

  it('set() with undefined value', () => {
    const fn = vi.fn();
    N.store.on('key', fn);
    N.store.set('key', undefined);
    expect(N.store.get('key')).toBeUndefined();
    expect(fn).toHaveBeenCalledTimes(1);
  });
});

describe('N.Core.store.on() — edge cases', () => {
  it('same function registered twice receives two calls', () => {
    const fn = vi.fn();
    N.store.on('key', fn);
    N.store.on('key', fn);
    N.store.set('key', 'val');
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('unsubscribing an already-unsubscribed listener does not error', () => {
    const fn = vi.fn();
    const unsub = N.store.on('key', fn);
    unsub();
    expect(() => unsub()).not.toThrow();
  });

  it('wildcard listener receives correct key name', () => {
    const fn = vi.fn();
    N.store.on('*', fn);
    N.store.set('alpha', 1);
    N.store.set('beta', 2);
    expect(fn).toHaveBeenCalledTimes(2);
    expect(fn).toHaveBeenCalledWith('alpha', 1, undefined);
    expect(fn).toHaveBeenCalledWith('beta', 2, undefined);
  });
});

describe('N.Core.store.init() — edge cases', () => {
  it('stores nested object defaults', () => {
    N.store.init({ nested: { a: 1, b: 2 } });
    const val = N.store.get('nested');
    expect(val).toEqual({ a: 1, b: 2 });
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
