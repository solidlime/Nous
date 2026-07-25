/* =================================================================
   CHAT SETTINGS MCP — MCP JSON rendering/parsing, skills list, JSON utils
   Namespace: N.Chat.settings.*
   Depends on: chat-settings.js (N.Chat.settings.save)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
"use strict";
var S = window.S;

// ------------------------------------------------------------------
// MCP JSON rendering / parsing
// ------------------------------------------------------------------
function renderMcpJson(servers) {
  const ta = document.getElementById("chat-mcp-json");
  if (!ta) return;
  if (!servers || servers.length === 0) {
    ta.value = '{\n  "mcpServers": {}\n}';
    return;
  }
  const mcpServers = {};
  (servers || []).forEach((srv) => {
    const entry = {};
    if (srv.transport === "http") {
      entry.url = srv.url || "";
      if (srv.headers && Object.keys(srv.headers).length)
        entry.headers = srv.headers;
    } else {
      entry.command = srv.command || "";
      if (srv.args && srv.args.length) entry.args = srv.args;
      if (srv.headers && Object.keys(srv.headers).length)
        entry.env = srv.headers;
    }
    mcpServers[srv.name] = entry;
  });
  ta.value = JSON.stringify({ mcpServers }, null, 2);

  /* ── Render MCP server list with Built-in badges ── */
  var listEl = document.getElementById("chat-mcp-server-list");
  if (listEl) {
    safeSetHTML(listEl, "");
    (servers || []).forEach(function (srv) {
      var isBuiltin = srv._builtin === true;
      var row = document.createElement("div");
      row.style.cssText =
        "display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--glass-border);";
      var nameSpan = document.createElement("span");
      nameSpan.style.cssText =
        "font-size:0.82rem;color:var(--text-secondary);font-weight:500;";
      nameSpan.textContent = srv.name;
      row.appendChild(nameSpan);
      if (isBuiltin) {
        var badge = document.createElement("span");
        badge.className = "builtin-badge";
        badge.textContent = "Built-in";
        row.appendChild(badge);
      }
      var spacer = document.createElement("span");
      spacer.style.cssText = "flex:1;";
      row.appendChild(spacer);
      if (!isBuiltin) {
        var delBtn = document.createElement("button");
        delBtn.className = "mem-action-btn del";
        delBtn.textContent = "削除";
        delBtn.style.cssText = "font-size:0.68rem;padding:2px 8px;";
        delBtn.onclick = function () {
          N.Chat.state.mcpServers = N.Chat.state.mcpServers.filter(function (s) {
            return s.name !== srv.name;
          });
          renderMcpJson(N.Chat.state.mcpServers);
        };
        row.appendChild(delBtn);
      }
      listEl.appendChild(row);
      renderMcpServerTools(listEl, srv);
    });
  }
}

function renderMcpServerTools(listEl, srv) {
  var toolsForServer = (N.Chat.state.mcpTools || []).filter(function(t) {
    return t.server === srv.name;
  });
  if (!toolsForServer.length) return;

  var collapsed = false;

  var head = document.createElement("div");
  head.style.cssText =
    "font-size:0.6rem;color:var(--text-muted);cursor:pointer;user-select:none;padding:1px 4px;";
  head.textContent = "▼ tools (" + toolsForServer.length + ")";

  var body = document.createElement("div");
  body.style.cssText =
    "display:flex;flex-wrap:wrap;gap:3px;padding:2px 0 4px 8px;";

  toolsForServer.forEach(function(tool) {
    var enabled =
      !(N.Chat.state.disabledTools &&
        N.Chat.state.disabledTools.has(tool.name));
    var badge = document.createElement("span");
    badge.textContent = tool.name;
    badge.title = (tool.description || "").slice(0, 100);
    badge.style.cssText =
      "font-size:0.6rem;padding:1px 5px;border-radius:3px;border:1px solid var(--glass-border);cursor:pointer;" +
      (enabled
        ? "background:var(--glass-bg);color:var(--text-secondary);"
        : "background:var(--bg-secondary);color:var(--text-muted);opacity:0.5;text-decoration:line-through;");
    badge.onclick = function(ev) {
      ev.stopPropagation();
      N.Chat.tools.toggle(tool.name);
      renderMcpJson(N.Chat.state.mcpServers);
    };
    body.appendChild(badge);
  });

  head.onclick = function() {
    collapsed = !collapsed;
    body.style.display = collapsed ? "none" : "flex";
    head.textContent =
      (collapsed ? "▶" : "▼") + " tools (" + toolsForServer.length + ")";
  };

  var wrapper = document.createElement("div");
  wrapper.style.cssText =
    "border-bottom:1px solid var(--glass-border);margin-bottom:2px;";
  wrapper.appendChild(head);
  wrapper.appendChild(body);
  listEl.appendChild(wrapper);
}

function parseMcpJson() {
  const ta = document.getElementById("chat-mcp-json");
  const errEl = document.getElementById("chat-mcp-json-error");
  if (!ta) return N.Chat.state.mcpServers;
  if (errEl) errEl.style.display = "none";
  const raw = ta.value.trim();
  if (!raw || raw === '{\n  "mcpServers": {}\n}') return [];
  try {
    const parsed = JSON.parse(raw);
    const dict = parsed.mcpServers || {};
    /* Preserve _builtin flags from original N.Chat.state.mcpServers */
    var builtinMap = {};
    (N.Chat.state.mcpServers || []).forEach(function (s) {
      if (s._builtin) builtinMap[s.name] = true;
    });
    return Object.entries(dict).map(([name, cfg]) => ({
      name,
      transport: cfg.url ? "http" : "stdio",
      url: cfg.url || "",
      command: cfg.command || "",
      args: cfg.args || [],
      headers: cfg.headers || cfg.env || {},
      enabled: true,
      _builtin: builtinMap[name] || false,
    }));
  } catch (e) {
    // Try loosened JSON parsing
    try {
      const loosened = loosenJson(raw);
      const parsed = JSON.parse(loosened);
      const dict = parsed.mcpServers || {};
      var builtinMap = {};
      (N.Chat.state.mcpServers || []).forEach(function (s) {
        if (s._builtin) builtinMap[s.name] = true;
      });
      return Object.entries(dict).map(([name, cfg]) => ({
        name,
        transport: cfg.url ? "http" : "stdio",
        url: cfg.url || "",
        command: cfg.command || "",
        args: cfg.args || [],
        headers: cfg.headers || cfg.env || {},
        enabled: true,
        _builtin: builtinMap[name] || false,
      }));
    } catch (e2) {
      if (errEl) {
        errEl.textContent = "JSON形式エラー: " + e2.message;
        errEl.style.display = "";
      }
      return N.Chat.state.mcpServers;
    }
  }
}

// ------------------------------------------------------------------
// Skills list rendering
// ------------------------------------------------------------------
const BUILTIN_SKILLS = ["search"];

function renderSkillsList(allSkills, enabledSkills) {
  const list = document.getElementById("chat-skills-list");
  if (!list) return;
  safeSetHTML(list, "");
  if (!allSkills || allSkills.length === 0) {
    safeSetHTML(list,
      '<div style="font-size:0.75rem;color:var(--text-muted);">スキルがありません</div>');
    return;
  }
  allSkills.forEach((skill) => {
    const enabled = (enabledSkills || []).includes(skill.name);
    const isBuiltin = BUILTIN_SKILLS.includes(skill.name);
    const item = document.createElement("div");
    item.style.cssText = "display:flex;align-items:center;gap:8px;";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = enabled;
    cb.id = "skill-cb-" + skill.name;
    cb.style.cssText =
      "width:14px;height:14px;accent-color:var(--accent-purple);cursor:pointer;";
    if (isBuiltin) {
      cb.disabled = true;
      cb.title = "Built-in スキルは削除できません";
    }
    cb.addEventListener("change", () => {
      if (cb.checked) {
        if (!N.Chat.state.enabledSkills.includes(skill.name))
          N.Chat.state.enabledSkills.push(skill.name);
      } else {
        N.Chat.state.enabledSkills = N.Chat.state.enabledSkills.filter((n) => n !== skill.name);
      }
      N.Chat.settings.save();
    });
    const label = document.createElement("label");
    label.htmlFor = cb.id;
    label.style.cssText =
      "font-size:0.78rem;color:var(--text-secondary);cursor:pointer;display:inline-flex;align-items:center;gap:6px;";
    label.title = skill.description || "";
    label.textContent = skill.name;
    if (isBuiltin) {
      var badge = document.createElement("span");
      badge.className = "builtin-badge";
      badge.textContent = "Built-in";
      label.appendChild(badge);
    }
    item.appendChild(cb);
    item.appendChild(label);
    list.appendChild(item);
  });
}

// ------------------------------------------------------------------
// JSON utilities
// ------------------------------------------------------------------
function loosenJson(text) {
  var s = text.trim();
  if (!s) return s;
  // Remove // line comments
  s = s.replace(/\/\/.*$/gm, '');
  // Remove /* */ block comments
  s = s.replace(/\/\*[\s\S]*?\*\//g, '');
  // Convert single-quoted keys/values to double-quoted (simple heuristic)
  s = s.replace(/'([^']*)'/g, function(m, inner) {
    return '"' + inner.replace(/"/g, '\\"') + '"';
  });
  // Quote unquoted keys: /(\s*)(\w+)(\s*):/ → $1"$2"$3:
  s = s.replace(/([{,]\s*)([a-zA-Z_]\w*)(\s*:)/g, '$1"$2"$3');
  // Remove trailing commas before } or ]
  s = s.replace(/,(\s*[}\]])/g, '$1');
  return s;
}

async function formatMcpJson() {
  var ta = document.getElementById("chat-mcp-json");
  var errDiv = document.getElementById("chat-mcp-json-error");
  if (!ta) return;
  var raw = ta.value.trim();
  if (!raw) { ta.value = '{\n  "mcpServers": {}\n}'; return; }
  try {
    // Try strict first
    var parsed = JSON.parse(raw);
    ta.value = JSON.stringify(parsed, null, 2);
    if (errDiv) errDiv.style.display = "none";
  } catch (e) {
    // Try loosened
    try {
      var parsed2 = JSON.parse(loosenJson(raw));
      ta.value = JSON.stringify(parsed2, null, 2);
      if (errDiv) errDiv.style.display = "none";
    } catch (e2) {
      if (errDiv) {
        errDiv.textContent = "整形できません: " + e2.message;
        errDiv.style.display = "block";
      }
    }
  }
}

// ------------------------------------------------------------------
// Register namespace additions
// ------------------------------------------------------------------
N.Chat.settings = N.Chat.settings || {};
Object.assign(N.Chat.settings, {
  BUILTIN_SKILLS: BUILTIN_SKILLS,
  renderMcpJson: renderMcpJson,
  parseMcpJson: parseMcpJson,
  renderSkills: renderSkillsList,
  loosenJson: loosenJson,
  formatMcpJson: formatMcpJson,
});

})(window.Nous);
