"""Admin tab section for the Nous Dashboard.

Renders the administration panel with vector store rebuild, database
statistics, and system information cards.
"""


def render_admin_tab() -> str:
    """Return the HTML for the Admin tab panel with skeleton grid."""
    return """
        <!-- ========== ADMIN TAB ========== -->
        <section id="tab-admin" class="tab-panel" role="tabpanel">
            <div style="margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="wrench"></i></span> Admin</h2>
            </div>
            <div id="admin-content">
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div></div>
                    <div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div></div>
                    <div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div></div>
                </div>
            </div>
        </section>"""


def render_admin_js() -> str:
    """Return the JavaScript for the loadAdmin() async function.

    Returns a plain string — no <script> tags.
    """
    return (
        "async function loadAdmin() {\n"
        "    const el = document.getElementById('admin-content');\n"
        "    try {\n"
        "        const [health, dashData] = await Promise.all([\n"
        "            api('/health'),\n"
        "            S.dashCache ? Promise.resolve(S.dashCache) : api('/api/dashboard/' + encodeURIComponent(S.persona))\n"
        "        ]);\n"
        "        if (!S.dashCache) S.dashCache = dashData;\n"
        "        const stats = dashData.stats || {};\n"
        "        const uptimeMs = Date.now() - S.initTime;\n"
        "        const uptimeStr = uptimeMs < 3600000 ? Math.floor(uptimeMs/60000) + 'm' : Math.floor(uptimeMs/3600000) + 'h ' + Math.floor((uptimeMs%3600000)/60000) + 'm';\n"
        "\n"
        "        el.innerHTML = `\n"
        '        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">\n'
        '            <div class="glass p-6">\n'
        '                <div class="card-title"><i data-lucide="refresh-cw"></i> Rebuild Vector Store</div>\n'
        '                <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:16px">Rebuild the Qdrant vector collection for the current persona. This may take a few minutes.</p>\n'
        '                <button id="rebuild-btn" class="glass-btn" style="width:100%"><i data-lucide="refresh-cw"></i> Rebuild Vectors</button>\n'
        '                <div id="rebuild-status" style="margin-top:12px;font-size:0.82rem;color:var(--text-muted);text-align:center"></div>\n'
        "            </div>\n"
        '            <div class="glass p-6">\n'
        '                <div class="card-title"><i data-lucide="layout-dashboard"></i> Database Stats</div>\n'
        '                <div style="display:grid;gap:10px">\n'
        '                    <div style="display:flex;justify-content:space-between"><span style="color:var(--text-muted)">Total Memories</span><span style="font-weight:600">${stats.total_count ?? \'--\'}</span></div>\n'
        '                    <div style="display:flex;justify-content:space-between"><span style="color:var(--text-muted)">Blocks</span><span style="font-weight:600">${(dashData.blocks || []).length}</span></div>\n'
        '                    <div style="display:flex;justify-content:space-between"><span style="color:var(--text-muted)">Unique Tags</span><span style="font-weight:600">${Object.keys(stats.tag_distribution || {}).length}</span></div>\n'
        '                    <div style="display:flex;justify-content:space-between"><span style="color:var(--text-muted)">Emotions Tracked</span><span style="font-weight:600">${Object.keys(stats.emotion_distribution || {}).length}</span></div>\n'
        '                    <div style="display:flex;justify-content:space-between"><span style="color:var(--text-muted)">Goals</span><span style="font-weight:600">${(dashData.goals || []).length}</span></div>\n'
        "                </div>\n"
        "            </div>\n"
        '            <div class="glass p-6">\n'
        '                <div class="card-title"><i data-lucide="clipboard-list"></i> System Info</div>\n'
        '                <div style="display:grid;gap:10px">\n'
        '                    <div style="display:flex;justify-content:space-between"><span style="color:var(--text-muted)">Version</span><span style="font-weight:600">${esc(health.version || \'--\')}</span></div>\n'
        "                    <div style=\"display:flex;justify-content:space-between\"><span style=\"color:var(--text-muted)\">Status</span><span class=\"badge ${health.status === 'ok' ? 'badge-green' : 'badge-red'}\">${esc(health.status || '--')}</span></div>\n"
        "                    <div style=\"display:flex;justify-content:space-between\"><span style=\"color:var(--text-muted)\">Qdrant</span><span class=\"badge ${health.qdrant === 'connected' ? 'badge-green' : 'badge-yellow'}\">${esc(health.qdrant || '--')}</span></div>\n"
        '                    <div style="display:flex;justify-content:space-between"><span style="color:var(--text-muted)">Session</span><span style="font-weight:600">${uptimeStr}</span></div>\n'
        '                    <div style="display:flex;justify-content:space-between"><span style="color:var(--text-muted)">Persona</span><span style="font-weight:600">${esc(S.persona)}</span></div>\n'
        "                </div>\n"
        "            </div>\n"
        "        </div>`;\n"
        "\n"
        "        // Rebuild button\n"
        "        document.getElementById('rebuild-btn').onclick = async () => {\n"
        "            const btn = document.getElementById('rebuild-btn');\n"
        "            const statusEl = document.getElementById('rebuild-status');\n"
        "            btn.disabled = true;\n"
        "            btn.textContent = '<i data-lucide=\"clock\"></i> Rebuilding...';\n"
        '            statusEl.innerHTML = \'<div class="progress-wrap"><div class="progress-bar progress-indeterminate"></div></div>\';\n'
        "            try {\n"
        "                await api('/api/admin/rebuild/' + encodeURIComponent(S.persona), { method: 'POST' });\n"
        '                statusEl.innerHTML = \'<span style="color:var(--accent-green)"><i data-lucide="check-circle"></i> Rebuild started successfully</span>\';\n'
        "                toast('Vector rebuild initiated', 'success');\n"
        "            } catch (e) {\n"
        "                statusEl.innerHTML = '<span style=\"color:var(--accent-red)\"><i data-lucide=\"x-circle\"></i> ' + esc(e.message) + '</span>';\n"
        "                toast('Rebuild failed: ' + e.message, 'error');\n"
        "            }\n"
        "            btn.disabled = false;\n"
        "            btn.textContent = '<i data-lucide=\"refresh-cw\"></i> Rebuild Vectors';\n"
        "        };\n"
        "        updateLastTime();\n"
        "    } catch (e) {\n"
        "        el.innerHTML = errorCard('Failed to load admin: ' + e.message);\n"
        "    }\n"
        "}"
    )
