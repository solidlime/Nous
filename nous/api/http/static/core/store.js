/* =================================================================
   STATE STORE — Centralized state with pub/sub
   ================================================================= */
;(function(N) {
"use strict";

var _state = {};
var _listeners = {};

var store = {
  get: function(key) {
    return _state[key];
  },

  set: function(key, value) {
    var old = _state[key];
    _state[key] = value;
    // Notify key-specific listeners
    var fns = _listeners[key] || [];
    fns.forEach(function(fn) { fn(value, old); });
    // Notify wildcard listeners
    var wild = _listeners["*"] || [];
    wild.forEach(function(fn) { fn(key, value, old); });
  },

  on: function(key, fn) {
    if (!_listeners[key]) _listeners[key] = [];
    _listeners[key].push(fn);
    return function unsubscribe() {
      var idx = _listeners[key].indexOf(fn);
      if (idx > -1) _listeners[key].splice(idx, 1);
    };
  },

  init: function(defaults) {
    var keys = Object.keys(defaults);
    keys.forEach(function(k) {
      if (_state[k] === undefined) {
        _state[k] = defaults[k];
      }
    });
  },

  dump: function() {
    return JSON.parse(JSON.stringify(_state));
  },
};

N.Core.store = store;

})(window.Nous);
