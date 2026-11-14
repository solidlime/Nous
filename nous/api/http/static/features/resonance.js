/* ================================================================
 *  Memory Resonance — 記憶のリアルタイム発火→収束 可視化
 *  Self-contained: vanilla JS, Canvas 2D, no deps, no base.js.
 *  Phases: IDLE → RECALL → PROPAGATE → CONVERGE
 *  NOTE: これはデモ。Graph タブの正は GraphFire（features/graph.js）。
 * ================================================================ */
;(function() {
"use strict";

/* ---- Config ---- */
var IDLE_NODE_CAP  = 120;   // idling background drift nodes
var SEARCH_LIMIT   = 20;    // /api/search limit
var NEIGHBOR_CAP   = 140;   // propagated (tag-adjacent) nodes max
var EDGE_CAP       = 320;   // drawn tag edges max
var RECALL_STEP_MS = 110;   // per-seed lighting interval
var FLASH_MS       = 600;
var PULSE_MS       = 850;
var CONVERGE_MS    = 950;

var COLORS = {
  active:   "#60a5fa",  // lit node (matches graph.js "related" highlight)
  seed:     "#007aff",  // search hit
  pulse:    "#bf5af2",
  ppr:      "#007aff",
  linkfire: "#bf5af2",
  recall:   "#30d158",
  drift:    "rgba(148,163,184,0.06)",  // slate, faint (graph.js edge color)
  edge:     "rgba(148,163,184,0.14)",
  text:     "rgba(235,235,245,0.72)"
};

var KIND_COLORS = {
  link_fire: COLORS.linkfire,
  recall_boost: COLORS.recall,
  ppr_hit: COLORS.ppr,
  replay_fire: "#7c7cf0",
  novelty_gate: "#ffd60a"
};

/* ---- DOM ---- */
var cv  = document.getElementById("resonance-canvas");
var ctx = cv.getContext("2d");
var el = {
  personaName: document.getElementById("resonance-persona-name"),
  status:      document.getElementById("resonance-status"),
  statusText:  document.getElementById("resonance-status-text"),
  form:        document.getElementById("resonance-form"),
  query:       document.getElementById("resonance-query"),
  btn:         document.getElementById("resonance-search-btn"),
  phase:       document.getElementById("resonance-phase"),
  results:     document.getElementById("resonance-results")
};

/* ---- State ---- */
var persona = new URLSearchParams(location.search).get("persona") || "herta";
var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

var graph = {};        // key -> { key, importance }
var adj = {};          // key -> [key]   (memory<->memory "tag" edges only)
var nodes = {};        // key -> node runtime {key,x,y,r,glow,flashSeed,flashColor,...}
var visibleKeys = [];  // keys currently drawn
var edges = [];        // {a,b} drawn edges
var pulses = [];       // {x1,y1,x2,y2,color,t0}
var idle = [];         // ambient drift nodes {x,y,vx,vy}

var running = false;   // a search sequence is active
var phase = "IDLE";    // IDLE|RECALL|PROPAGATE|CONVERGE
var phaseT0 = 0;
var runToken = 0;

var es = null;
var searchAbort = null;
var graphAbort = null;

/* ---- Canvas / HiDPI ---- */
var W = 0, H = 0, DPR = 1;
function resize() {
  DPR = Math.min(window.devicePixelRatio || 1, 2);
  W = window.innerWidth; H = window.innerHeight;
  cv.width = Math.floor(W * DPR);
  cv.height = Math.floor(H * DPR);
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
}
window.addEventListener("resize", function() { resize(); reflowSpine(); });

/* ---- Graph loading ---- */
function loadGraph() {
  if (graphAbort) graphAbort.abort();
  graphAbort = new AbortController();
  return fetch("/api/graph/" + encodeURIComponent(persona), { signal: graphAbort.signal })
    .then(function(r) { return r.ok ? r.json() : Promise.reject(new Error("graph " + r.status)); })
    .then(function(d) {
      graph = {};
      adj = {};
      (d.nodes || []).forEach(function(n) {
        if (!/^memory/.test(n.key)) return;
        graph[n.key] = { key: n.key, importance: Number(n.importance) || 0 };
        adj[n.key] = [];
      });
      (d.edges || []).forEach(function(e) {
        if (e.type !== "tag") return;
        if (!graph[e.source] || !graph[e.target] || e.source === e.target) return;
        adj[e.source].push(e.target);
        adj[e.target].push(e.source);
      });
      buildIdleField();
    })
    .catch(function(err) {
      if (err && err.name === "AbortError") return;
      // no graph -> still usable (search hits float alone)
      buildIdleField();
    });
}

/* ---- Idle ambient field ---- */
function buildIdleField() {
  idle = [];
  var keys = Object.keys(graph).slice(0, IDLE_NODE_CAP);
  keys.forEach(function() {
    idle.push({
      x: Math.random() * W,
      y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.08,
      vy: (Math.random() - 0.5) * 0.08,
      r: 1 + Math.random() * 2
    });
  });
}

/* ---- SSOT status chip ---- */
function setStatus(variant, label) {
  el.status.classList.toggle("live", variant === "live");
  el.status.classList.toggle("standby", variant !== "live");
  el.statusText.textContent = label;
}
function setPhase(label) {
  phase = label;
  el.phase.textContent = label;
}

/* ---- SSE (visibility-gated) ---- */
function connectSSE() {
  disconnectSSE();
  try {
    es = new EventSource("/api/memory/wiring/stream?persona=" + encodeURIComponent(persona));
  } catch (e) {
    setStatus("standby", "STANDBY");
    return;
  }
  es.addEventListener("connected", function() { setStatus("live", "SIGNAL LIVE"); });
  es.addEventListener("wiring", function(ev) {
    var msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    onWiring(msg);
  });
  es.onerror = function() { setStatus("standby", "STANDBY"); }; // EventSource auto-reconnects
}
function disconnectSSE() {
  if (es) { es.close(); es = null; }
  setStatus("standby", "STANDBY");
}

document.addEventListener("visibilitychange", function() {
  if (document.visibilityState === "hidden") {
    disconnectSSE();
    if (searchAbort) searchAbort.abort();
    if (graphAbort) graphAbort.abort();
    running = false;
    el.btn.disabled = false;
  } else {
    connectSSE();
  }
});

/* ---- SSE event → pulse ---- */
function onWiring(m) {
  if (!m || !m.kind || m.kind === "monologue") return;
  var color = KIND_COLORS[m.kind] || COLORS.pulse;
  var a = m.source ? nodes[m.source] : null;
  var b = m.target && nodes[m.target] ? nodes[m.target] : null;
  if (a && b) {
    // pulse source→target when both endpoints are drawn
    pulses.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y, color: color, t0: now() });
    b.flashSeed = now(); b.flashColor = color;
  } else if (a) {
    // ppr_hit etc.: ring flash on the source node
    a.flashSeed = now(); a.flashColor = color;
  }
}

/* ---- Search sequence ---- */
function parseResults(d) {
  return (d.results || []).map(function(r) {
    var mem = r.memory || {};
    return {
      key:   mem.key || "",
      score: Number(r.score) || 0,
      content: String(mem.content || ""),
      tags:  Array.isArray(mem.tags) ? mem.tags : [],
      importance: Number(mem.importance) || 0
    };
  }).filter(function(r) { return r.key.indexOf("memory") === 0; });
}

function collectNeighbors(hitKeys) {
  // BFS through tag adjacency, step lights gradually
  var seen = {}, layers = [], frontier = hitKeys.slice();
  hitKeys.forEach(function(k) { seen[k] = true; });
  var layer = 0;
  while (frontier.length && layer < 7 && visibleCount() + frontier.length < NEIGHBOR_CAP) {
    var next = [];
    frontier.forEach(function(k) {
      (adj[k] || []).forEach(function(nk) {
        if (seen[nk] || !graph[nk]) return;
        if (visibleCount() >= NEIGHBOR_CAP) return;
        seen[nk] = true;
        next.push(nk);
        edges.push({ a: k, b: nk });
      });
    });
    if (!next.length) break;
    layers.push(next);
    frontier = next;
    layer++;
  }
  return layers;
}
function visibleCount() { return visibleKeys.length; }

function layoutActives(hitKeys, layers) {
  // results on a wide arc around canvas center, neighbors in rings behind
  var cx = W * 0.42, cy = H * 0.48;
  var arcR = Math.min(W, H) * 0.28;
  var actives = {};
  hitKeys.forEach(function(k, i) {
    var ang = -Math.PI * 0.85 + (Math.PI * 1.15) * (hitKeys.length > 1 ? i / (hitKeys.length - 1) : 0.5);
    place(k, cx + Math.cos(ang) * arcR, cy + Math.sin(ang) * arcR * 0.75, true);
    actives[k] = true;
  });
  layers.forEach(function(layer, li) {
    layer.forEach(function(k, i) {
      var ang = (i / Math.max(layer.length, 1)) * Math.PI * 2 + li * 0.7;
      var r = arcR * (0.55 + li * 0.28);
      place(k, cx + Math.cos(ang) * r, cy + Math.sin(ang) * r * 0.72, false);
      actives[k] = true;
    });
  });
  // unique edges among drawn nodes
  var uniq = [], seen = {};
  edges.forEach(function(e) {
    if (!nodes[e.a] || !nodes[e.b]) return;
    var id = e.a < e.b ? e.a + "|" + e.b : e.b + "|" + e.a;
    if (seen[id]) return;
    seen[id] = true; uniq.push(e);
  });
  edges = uniq.slice(0, EDGE_CAP);
  visibleKeys = Object.keys(actives);
}

function place(key, x, y, isSeed) {
  var g = graph[key] || { importance: 0.4 };
  nodes[key] = {
    key: key, x: x, y: y, sx: x, sy: y, // sx/sy = converge origin
    r: 4 + g.importance * 8,
    isSeed: !!isSeed,
    glow: 0, flashSeed: 0, flashColor: null,
    tx: x, ty: y, lit: false
  };
}

el.form.addEventListener("submit", function(ev) {
  ev.preventDefault();
  if (running) return; // no concurrent runs
  var q = el.query.value.trim();
  if (!q) return;
  runSearch(q);
});

function runSearch(q) {
  running = true;
  el.btn.disabled = true;
  var token = ++runToken;
  if (searchAbort) searchAbort.abort();
  searchAbort = new AbortController();
  resetScene();
  setPhase("RECALL");

  fetch("/api/search/" + encodeURIComponent(persona) +
        "?q=" + encodeURIComponent(q) + "&limit=" + SEARCH_LIMIT,
        { signal: searchAbort.signal })
    .then(function(r) { return r.ok ? r.json() : Promise.reject(new Error("search " + r.status)); })
    .then(function(d) {
      if (token !== runToken) return;
      var hits = parseResults(d).slice(0, SEARCH_LIMIT);
      if (!hits.length) { finishRun("NO RESONANCE"); renderResults([], ""); return; }
      return loadGraphIfNeeded().then(function() {
        if (token !== runToken) return;
        startSequence(hits, q);
      });
    })
    .catch(function(err) {
      if (err && err.name === "AbortError") return;
      finishRun("SEARCH FAILED");
    });
}

function loadGraphIfNeeded() {
  return Object.keys(graph).length ? Promise.resolve() : loadGraph();
}

function resetScene() {
  nodes = {}; edges = []; pulses = []; visibleKeys = [];
}

function startSequence(hits, q) {
  var hitKeys = hits.map(function(h) { return h.key; }).filter(function(k) { return graph[k]; });
  var litKeys = hitKeys.length ? hitKeys : [];
  edges = [];
  var layers = collectNeighbors(litKeys);
  layoutActives(litKeys, layers);
  currentHits = hits;

  // Phase 1: RECALL — light seeds one by one
  var step = reduceMotion ? RECALL_STEP_MS / 4 : RECALL_STEP_MS;
  litKeys.forEach(function(k, i) {
    setTimeout(function() {
      if (!nodes[k]) return;
      nodes[k].lit = true;
      nodes[k].glow = 1;
      nodes[k].flashSeed = now();
      nodes[k].flashColor = COLORS.seed;
    }, i * step);
  });
  var recallDone = litKeys.length * step + 120;

  // Phase 2: PROPAGATE — reveal layers
  var propStart = recallDone + (reduceMotion ? 40 : 420);
  setTimeout(function() { if (running) setPhase("PROPAGATE"); }, propStart);
  layers.forEach(function(layer, li) {
    setTimeout(function() {
      layer.forEach(function(k) {
        if (nodes[k]) { nodes[k].lit = true; nodes[k].glow = 0.4; }
      });
    }, propStart + li * (reduceMotion ? 30 : 200));
  });
  var propDone = propStart + layers.length * (reduceMotion ? 30 : 200) + 100;

  // Phase 3: CONVERGE — spine alignment, then results panel
  setTimeout(function() {
    if (!running) return;
    setPhase("CONVERGE");
    phaseT0 = now();
    spineTargets(currentHits);
    renderResults(currentHits, q);
  }, propDone + (reduceMotion ? 40 : 500));

  setTimeout(function() { finishRun(""); }, propDone + (reduceMotion ? 60 : 500) + (reduceMotion ? 150 : CONVERGE_MS));
}

var currentHits = [];

function spineTargets(hits) {
  var x = W - 240;
  if (window.innerWidth < 768) x = W * 0.3;
  var topY = 130, gap = Math.min(64, (H - 260) / Math.max(hits.length, 1));
  hits.forEach(function(h, i) {
    var n = nodes[h.key];
    if (!n) return;
    n.sx = n.x; n.sy = n.y;
    n.tx = x + (i % 3) * 14;
    n.ty = Math.min(topY + i * gap, H - 90);
  });
}

function finishRun(label) {
  if (label) setPhase(label);
  running = false;
  el.btn.disabled = false;
}

/* ---- Results panel (XSS-safe: textContent only) ---- */
function excerpt(s, max) {
  s = s.replace(/\s+/g, " ").trim();
  return s.length > max ? s.slice(0, max) + "…" : s;
}

function renderResults(hits, q) {
  el.results.textContent = "";
  if (!hits.length) {
    var empty = document.createElement("p");
    empty.className = "resonance-content";
    empty.textContent = "共鳴なし — query: " + q;
    el.results.appendChild(empty);
    return;
  }
  hits.forEach(function(h, i) {
    var card = document.createElement("article");
    card.className = "resonance-result";

    var top = document.createElement("div");
    top.className = "resonance-result-top";
    var rank = document.createElement("span");
    rank.className = "resonance-rank";
    rank.textContent = "#" + (i + 1);
    var score = document.createElement("span");
    score.className = "resonance-score";
    score.textContent = "score " + h.score.toFixed(4);
    top.appendChild(rank); top.appendChild(score);

    card.appendChild(top);

    if (h.tags.length) {
      var tags = document.createElement("div");
      tags.className = "resonance-tags";
      h.tags.slice(0, 6).forEach(function(t) {
        var tag = document.createElement("span");
        tag.className = "resonance-tag";
        tag.textContent = String(t);
        tags.appendChild(tag);
      });
      card.appendChild(tags);
    }

    var body = document.createElement("p");
    body.className = "resonance-content";
    body.textContent = excerpt(h.content, 110);
    card.appendChild(body);

    el.results.appendChild(card);

    setTimeout(function() { card.classList.add("shown"); },
      reduceMotion ? 0 : Math.min(i * 60, 600));
  });
}

/* ---- Render loop ---- */
function now() { return performance.now(); }

function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }

function draw(ts) {
  ctx.clearRect(0, 0, W, H);

  // ambient drift field
  ctx.fillStyle = COLORS.drift;
  idle.forEach(function(d) {
    d.x += d.vx; d.y += d.vy;
    if (d.x < -4) d.x = W + 4; if (d.x > W + 4) d.x = -4;
    if (d.y < -4) d.y = H + 4; if (d.y > H + 4) d.y = -4;
    ctx.beginPath(); ctx.arc(d.x, d.y, d.r, 0, 6.2832); ctx.fill();
  });

  // edges
  ctx.lineWidth = 0.6;
  ctx.strokeStyle = COLORS.edge;
  edges.forEach(function(e) {
    var a = nodes[e.a], b = nodes[e.b];
    if (!a || !b || !a.lit && !b.lit) return;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
    ctx.stroke();
  });

  // converge easing applies to node positions toward targets
  var convergeK = 1;
  if (phase === "CONVERGE" && phaseT0) {
    convergeK = easeOutCubic(Math.min((ts - phaseT0) / (reduceMotion ? 150 : CONVERGE_MS), 1));
  }

  // nodes
  visibleKeys.forEach(function(key) {
    var n = nodes[key];
    if (!n) return;
    var x = n.x, y = n.y;
    if (phase === "CONVERGE" && n.tx !== n.x) {
      x = n.sx + (n.tx - n.sx) * convergeK;
      y = n.sy + (n.ty - n.sy) * convergeK;
      n.x = x; n.y = y; // let pulses track converged positions
    }

    // glow decay
    if (n.glow > 0.05) n.glow *= 0.985;

    var r = n.r * (n.isSeed ? 1 : 0.85);
    if (n.lit) {
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 6.2832);
      var alpha = 0.25 + n.glow * 0.7;
      ctx.fillStyle = n.isSeed
        ? "rgba(0,122,255," + alpha + ")"
        : "rgba(96,165,250," + (alpha * 0.75) + ")";
      ctx.fill();
    } else {
      ctx.beginPath();
      ctx.arc(x, y, r * 0.6, 0, 6.2832);
      ctx.fillStyle = "rgba(148,163,184,0.10)";
      ctx.fill();
    }

    // flash ring
    if (n.flashSeed) {
      var ft = (ts - n.flashSeed) / FLASH_MS;
      if (ft < 1) {
        ctx.beginPath();
        ctx.arc(x, y, r + ft * 26, 0, 6.2832);
        ctx.strokeStyle = hexA(n.flashColor || COLORS.active, 1 - ft);
        ctx.lineWidth = 1.6;
        ctx.stroke();
      } else {
        n.flashSeed = 0;
      }
    }
  });

  // pulses
  var keep = [];
  pulses.forEach(function(p) {
    var t = (ts - p.t0) / (reduceMotion ? 200 : PULSE_MS);
    if (t >= 1) return;
    keep.push(p);
    var k = easeOutCubic(t);
    var px = p.x1 + (p.x2 - p.x1) * k;
    var py = p.y1 + (p.y2 - p.y1) * k;
    ctx.beginPath();
    ctx.arc(px, py, 3, 0, 6.2832);
    ctx.fillStyle = hexA(p.color, 0.9 * (1 - t * 0.4));
    ctx.fill();
    // trail
    var tx = p.x1 + (p.x2 - p.x1) * Math.max(k - 0.08, 0);
    var ty = p.y1 + (p.y2 - p.y1) * Math.max(k - 0.08, 0);
    ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(px, py);
    ctx.strokeStyle = hexA(p.color, 0.35 * (1 - t));
    ctx.lineWidth = 2;
    ctx.stroke();
  });
  pulses = keep;

  // cap
  if (pulses.length > 80) pulses = pulses.slice(-80);
}

function hexA(hex, a) {
  var r = parseInt(hex.slice(1, 3), 16);
  var g = parseInt(hex.slice(3, 5), 16);
  var b = parseInt(hex.slice(5, 7), 16);
  return "rgba(" + r + "," + g + "," + b + "," + Math.max(a, 0) + ")";
}

function reflowSpine() {
  if (phase !== "CONVERGE" && running === false) return;
  if (currentHits.length && phase === "CONVERGE") spineTargets(currentHits);
}

/* ---- Boot ---- */
function loop(ts) { draw(ts); requestAnimationFrame(loop); }

el.personaName.textContent = persona;
resize();
loadGraph();
connectSSE();
requestAnimationFrame(loop);

})();
