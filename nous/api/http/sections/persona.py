"""Persona Management tab section for the Nous Dashboard.

Provides UI for creating, editing, switching, and deleting personas.
Each persona is displayed as a card showing memory count, last conversation,
and current emotion state.
"""


def render_persona_tab() -> str:
    """Return the HTML for the Personas tab panel."""
    return (
        "<!-- ========== PERSONAS TAB ========== -->"
        '<section id="tab-personas" class="tab-panel" role="tabpanel">'
        '<div style="margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">'
        '<h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;">'
        '<i data-lucide="user" style="width:1.4rem;height:1.4rem"></i> Personas</h2>'
        "</div>"
        '<div id="personas-content">'
        # --- Header with create button ---
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px">'
        '<h3 style="font-size:1.1rem;font-weight:600;color:var(--text-primary)">Manage Personas</h3>'
        '<button onclick="showCreatePersona()" class="glass-btn" style="padding:8px 20px">'
        "\u2795 New Persona</button>"
        "</div>"
        # --- Persona cards grid ---
        '<div id="persona-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px">'
        '<div style="text-align:center;color:var(--text-muted);padding:40px">Loading personas...</div>'
        "</div>"
        "</div>"
        # --- Create persona modal ---
        '<div id="create-persona-modal" style="display:none;position:fixed;inset:0;'
        "background:rgba(0,0,0,0.6);backdrop-filter:blur(8px);z-index:1000;"
        'align-items:center;justify-content:center">'
        '<div class="glass p-6" style="max-width:400px;width:90%;border-radius:16px">'
        '<h3 style="font-size:1.2rem;font-weight:600;color:var(--text-primary);margin-bottom:16px">'
        "\u2795 Create New Persona</h3>"
        '<input type="text" id="new-persona-name" class="glass-input" '
        'placeholder="Persona name (alphanumeric, _, -)" '
        'style="width:100%;padding:10px 16px;margin-bottom:8px;box-sizing:border-box" maxlength="50">'
        '<p style="font-size:0.8rem;color:var(--text-muted);margin-bottom:16px">'
        "Allowed: letters, numbers, underscores, hyphens (1-50 chars)</p>"
        '<div style="display:flex;gap:12px;justify-content:flex-end">'
        '<button onclick="hideCreatePersona()" class="glass-btn" style="padding:8px 20px">Cancel</button>'
        '<button onclick="createPersona()" class="glass-btn" '
        'style="padding:8px 20px;background:var(--accent-purple);color:white">Create</button>'
        "</div>"
        "</div>"
        "</div>"
        # --- Profile edit modal ---
        '<div id="profile-edit-modal" style="display:none;position:fixed;inset:0;'
        "background:rgba(0,0,0,0.6);backdrop-filter:blur(8px);z-index:1000;"
        'align-items:center;justify-content:center">'
        '<div class="glass p-6" style="max-width:500px;width:90%;border-radius:16px;'
        'max-height:80vh;overflow-y:auto">'
        '<h3 style="font-size:1.2rem;font-weight:600;color:var(--text-primary);margin-bottom:16px">'
        '<i data-lucide="pencil"></i> Edit Profile: <span id="edit-persona-name-display"></span></h3>'
        '<input type="hidden" id="edit-persona-name">'
        # -- User Name --
        '<div style="margin-bottom:16px">'
        '<label style="display:block;font-size:0.85rem;color:var(--text-muted);margin-bottom:4px">User Name</label>'
        '<input type="text" id="edit-user-name" class="glass-input" '
        'style="width:100%;padding:8px 12px;box-sizing:border-box" placeholder="User\'s name">'
        "</div>"
        # -- User Nickname --
        '<div style="margin-bottom:16px">'
        '<label style="display:block;font-size:0.85rem;color:var(--text-muted);margin-bottom:4px">User Nickname</label>'
        '<input type="text" id="edit-user-nickname" class="glass-input" '
        'style="width:100%;padding:8px 12px;box-sizing:border-box" placeholder="Nickname">'
        "</div>"
        # -- Preferred Address --
        '<div style="margin-bottom:16px">'
        '<label style="display:block;font-size:0.85rem;color:var(--text-muted);margin-bottom:4px">Preferred Address</label>'
        '<input type="text" id="edit-user-preferred-address" class="glass-input" '
        'style="width:100%;padding:8px 12px;box-sizing:border-box" placeholder="How to address user">'
        "</div>"
        # -- Persona Nickname --
        '<div style="margin-bottom:16px">'
        '<label style="display:block;font-size:0.85rem;color:var(--text-muted);margin-bottom:4px">Persona Nickname</label>'
        '<input type="text" id="edit-persona-nickname" class="glass-input" '
        'style="width:100%;padding:8px 12px;box-sizing:border-box" placeholder="Persona\'s nickname">'
        "</div>"
        # -- Relationship Status --
        '<div style="margin-bottom:16px">'
        '<label style="display:block;font-size:0.85rem;color:var(--text-muted);margin-bottom:4px">Relationship Status</label>'
        '<input type="text" id="edit-relationship-status" class="glass-input" '
        'style="width:100%;padding:8px 12px;box-sizing:border-box" placeholder="e.g. friend, partner, assistant">'
        "</div>"
        # -- Modal buttons --
        '<div style="display:flex;gap:12px;justify-content:flex-end;margin-top:20px">'
        '<button onclick="hideEditProfile()" class="glass-btn" style="padding:8px 20px">Cancel</button>'
        '<button onclick="saveProfile()" class="glass-btn" '
        'style="padding:8px 20px;background:var(--accent-purple);color:white">Save</button>'
        "</div>"
        "</div>"
        "</div>"
        "</section>"
    )


def render_persona_js() -> str:
    """Return the JavaScript for the Personas tab.

    Includes: loadPersonas, showCreatePersona, hideCreatePersona,
    createPersona, editPersonaProfile, hideEditProfile, saveProfile,
    deletePersona, switchPersonaTo.
    """
    return (
        "// === Persona Management Tab ===\n"
        "\n"
        "async function loadPersonas() {\n"
        "    var grid = document.getElementById('persona-grid');\n"
        "    if (!grid) return;\n"
        "    grid.innerHTML = '<div style=\"text-align:center;color:var(--text-muted);padding:40px\">Loading personas...</div>';\n"
        "    try {\n"
        "        var listData = await api('/api/personas');\n"
        "        var personas = listData.personas || [];\n"
        "        if (personas.length === 0) {\n"
        "            grid.innerHTML = '<div style=\"text-align:center;color:var(--text-muted);padding:40px\">No personas found. Create one!</div>';\n"
        "            return;\n"
        "        }\n"
        "        var details = await Promise.allSettled(\n"
        "            personas.map(function(p) { return api('/api/dashboard/' + encodeURIComponent(p)); })\n"
        "        );\n"
        "        var html = '';\n"
        "        var emotionEmoji = {\n"
        "            joy: '<i data-lucide=\"smile\"></i>', sadness: '<i data-lucide=\"frown\"></i>', anger: '<i data-lucide=\"angry\"></i>', fear: '<i data-lucide=\"anxiety\"></i>',\n"
        "            surprise: '<i data-lucide=\"surprise\"></i>', disgust: '<i data-lucide=\"dizzy\"></i>', trust: '<i data-lucide=\"handshake\"></i>', anticipation: '<i data-lucide=\"star\"></i>',\n"
        "            love: '\\u2764\\ufe0f', neutral: '<i data-lucide=\"meh\"></i>'\n"
        "        };\n"
        "        personas.forEach(function(name, i) {\n"
        "            var d = details[i].status === 'fulfilled' ? details[i].value : {};\n"
        "            var stats = d.stats || {};\n"
        "            var ctx = d.context || {};\n"
        "            var isActive = name === S.persona;\n"
        "            var lastConv = ctx.last_conversation_time;\n"
        "            var memCount = stats.total_count || 0;\n"
        "            var emotion = ctx.emotion || 'neutral';\n"
        "            var emotionIntensity = ctx.emotion_intensity != null ? ctx.emotion_intensity : 0;\n"
        "            var emoji = emotionEmoji[emotion] || '<i data-lucide=\"meh\"></i>';\n"
        "            var activeBorder = isActive\n"
        "                ? 'border:2px solid var(--accent-purple);box-shadow:0 0 20px rgba(168,85,247,0.3)'\n"
        "                : 'border:1px solid var(--glass-border)';\n"
        "            var activeBadge = isActive\n"
        "                ? '<span style=\"font-size:0.75rem;background:var(--accent-purple);color:white;padding:2px 8px;border-radius:9999px;margin-left:8px\">Active</span>'\n"
        "                : '';\n"
        "            var switchBtn = !isActive\n"
        '                ? \'<button onclick="switchPersonaTo(\\\'\' + esc(name) + \'\\\')" class="glass-btn" style="padding:6px 14px;font-size:0.85rem"><i data-lucide="refresh-cw"></i> Switch</button>\'\n'
        "                : '';\n"
        "            var deleteStyle = 'padding:6px 14px;font-size:0.85rem';\n"
        "            html += '<div class=\"glass glass-hoverable p-5\" style=\"border-radius:12px;' + activeBorder + '\">'\n"
        "                + '<div style=\"display:flex;justify-content:space-between;align-items:center;margin-bottom:12px\">'\n"
        "                + '<div style=\"font-size:1.1rem;font-weight:600;color:var(--text-primary)\">'\n"
        "                + '<i data-lucide=\"user\"></i> ' + esc(name) + activeBadge\n"
        "                + '</div></div>'\n"
        "                + '<div style=\"display:flex;flex-direction:column;gap:6px;font-size:0.9rem;color:var(--text-muted);margin-bottom:16px\">'\n"
        "                + '<div><i data-lucide=\"edit-3\"></i> <strong>' + memCount + '</strong> memories</div>'\n"
        "                + '<div><i data-lucide=\"message-circle\"></i> Last: ' + (lastConv ? relativeTime(lastConv) : 'Never') + '</div>'\n"
        "                + '<div>' + emoji + ' ' + esc(emotion) + ' (' + emotionIntensity.toFixed(1) + ')</div>'\n"
        "                + (function() { \n"
        "                    var parts = []; \n"
        "                    if (stats.fatigue != null) parts.push('<i data-lucide=\"flame\"></i>Fatigue:' + (stats.fatigue*100).toFixed(0) + '%'); \n"
        "                    if (stats.warmth != null) parts.push('<i data-lucide=\"flower\"></i>Warmth:' + (stats.warmth*100).toFixed(0) + '%'); \n"
        "                    if (stats.arousal != null) parts.push('<i data-lucide=\"zap\"></i>Arousal:' + (stats.arousal*100).toFixed(0) + '%'); \n"
        "                    if (stats.pain != null && stats.pain > 0) parts.push('<i data-lucide=\"activity\"></i>Pain:' + (stats.pain*100).toFixed(0) + '%'); \n"
        "                    return parts.length > 0 ? '<div style=\"font-size:0.78rem;color:var(--text-muted);margin-top:4px\">' + parts.join(' · ') + '</div>' : ''; \n"
        "                })()\n"
        "                + '</div>'\n"
        "                + '<div style=\"display:flex;gap:8px;flex-wrap:wrap\">'\n"
        "                + '<button onclick=\"editPersonaProfile(\\'' + esc(name) + '\\')\" class=\"glass-btn\" style=\"padding:6px 14px;font-size:0.85rem\">\\u270f\\ufe0f Edit</button>'\n"
        "                + switchBtn\n"
        "                + '<button onclick=\"deletePersona(\\'' + esc(name) + '\\')\" class=\"glass-btn\" style=\"' + deleteStyle + '\"><i data-lucide=\"trash-2\"></i> Delete</button>'\n"
        "                + '</div></div>';\n"
        "        });\n"
        "        grid.innerHTML = html;\n"
        "    } catch (e) {\n"
        "        grid.innerHTML = '<div style=\"text-align:center;color:#ef4444;padding:40px\">Failed to load personas: ' + esc(e.message) + '</div>';\n"
        "    }\n"
        "}\n"
        "\n"
        "// --- Create Persona ---\n"
        "function showCreatePersona() {\n"
        "    var modal = document.getElementById('create-persona-modal');\n"
        "    modal.style.display = 'flex';\n"
        "    document.getElementById('new-persona-name').value = '';\n"
        "    document.getElementById('new-persona-name').focus();\n"
        "}\n"
        "\n"
        "function hideCreatePersona() {\n"
        "    document.getElementById('create-persona-modal').style.display = 'none';\n"
        "}\n"
        "\n"
        "async function createPersona() {\n"
        "    var name = document.getElementById('new-persona-name').value.trim();\n"
        "    if (!name) { toast('Please enter a name', 'error'); return; }\n"
        "    if (!/^[a-zA-Z0-9_-]{1,50}$/.test(name)) {\n"
        "        toast('Name must be 1-50 chars: letters, numbers, _, -', 'error');\n"
        "        return;\n"
        "    }\n"
        "    try {\n"
        "        await api('/api/personas', {\n"
        "            method: 'POST',\n"
        "            headers: {'Content-Type': 'application/json'},\n"
        "            body: JSON.stringify({name: name})\n"
        "        });\n"
        "        toast('Persona \"' + name + '\" created!', 'success');\n"
        "        hideCreatePersona();\n"
        "        loadPersonas();\n"
        "    } catch (e) {\n"
        "        toast('Failed to create persona: ' + e.message, 'error');\n"
        "    }\n"
        "}\n"
        "\n"
        "// --- Edit Profile ---\n"
        "async function editPersonaProfile(name) {\n"
        "    var modal = document.getElementById('profile-edit-modal');\n"
        "    document.getElementById('edit-persona-name').value = name;\n"
        "    document.getElementById('edit-persona-name-display').textContent = name;\n"
        "    try {\n"
        "        var data = await api('/api/dashboard/' + encodeURIComponent(name));\n"
        "        var ctx = data.context || {};\n"
        "        var ui = ctx.user_info || {};\n"
        "        var pi = ctx.persona_info || {};\n"
        "        document.getElementById('edit-user-name').value = ui.name || '';\n"
        "        document.getElementById('edit-user-nickname').value = ui.nickname || '';\n"
        "        document.getElementById('edit-user-preferred-address').value = ui.preferred_address || '';\n"
        "        document.getElementById('edit-persona-nickname').value = pi.nickname || '';\n"
        "        document.getElementById('edit-relationship-status').value = ctx.relationship_status || '';\n"
        "    } catch (e) {\n"
        "        document.getElementById('edit-user-name').value = '';\n"
        "        document.getElementById('edit-user-nickname').value = '';\n"
        "        document.getElementById('edit-user-preferred-address').value = '';\n"
        "        document.getElementById('edit-persona-nickname').value = '';\n"
        "        document.getElementById('edit-relationship-status').value = '';\n"
        "    }\n"
        "    modal.style.display = 'flex';\n"
        "}\n"
        "\n"
        "function hideEditProfile() {\n"
        "    document.getElementById('profile-edit-modal').style.display = 'none';\n"
        "}\n"
        "\n"
        "async function saveProfile() {\n"
        "    var name = document.getElementById('edit-persona-name').value;\n"
        "    var userName = document.getElementById('edit-user-name').value.trim();\n"
        "    var userNickname = document.getElementById('edit-user-nickname').value.trim();\n"
        "    var userPreferred = document.getElementById('edit-user-preferred-address').value.trim();\n"
        "    var personaNickname = document.getElementById('edit-persona-nickname').value.trim();\n"
        "    var relStatus = document.getElementById('edit-relationship-status').value.trim();\n"
        "    var body = {};\n"
        "    var userInfo = {};\n"
        "    if (userName) userInfo.name = userName;\n"
        "    if (userNickname) userInfo.nickname = userNickname;\n"
        "    if (userPreferred) userInfo.preferred_address = userPreferred;\n"
        "    if (Object.keys(userInfo).length > 0) body.user_info = userInfo;\n"
        "    var personaInfo = {};\n"
        "    if (personaNickname) personaInfo.nickname = personaNickname;\n"
        "    if (Object.keys(personaInfo).length > 0) body.persona_info = personaInfo;\n"
        "    if (relStatus) body.relationship_status = relStatus;\n"
        "    if (Object.keys(body).length === 0) {\n"
        "        toast('No changes to save', 'info');\n"
        "        return;\n"
        "    }\n"
        "    try {\n"
        "        await api('/api/personas/' + encodeURIComponent(name) + '/profile', {\n"
        "            method: 'PUT',\n"
        "            headers: {'Content-Type': 'application/json'},\n"
        "            body: JSON.stringify(body)\n"
        "        });\n"
        "        toast('Profile updated!', 'success');\n"
        "        hideEditProfile();\n"
        "        loadPersonas();\n"
        "    } catch (e) {\n"
        "        toast('Failed to update profile: ' + e.message, 'error');\n"
        "    }\n"
        "}\n"
        "\n"
        "// --- Delete Persona ---\n"
        "async function deletePersona(name) {\n"
        "    if (name === S.persona) {\n"
        "        toast('Cannot delete the active persona. Switch first.', 'error');\n"
        "        return;\n"
        "    }\n"
        "    showConfirm('Are you sure you want to delete persona \\\"' + name + '\\\"?\\\\nAll memories will be permanently lost.', async function() {\n"
        "        try {\n"
        "            await api('/api/personas/' + encodeURIComponent(name), { method: 'DELETE' });\n"
        "            toast('Persona \"' + name + '\" deleted', 'success');\n"
        "            loadPersonas();\n"
        "        } catch (e) {\n"
        "            toast('Failed to delete persona: ' + e.message, 'error');\n"
        "        }\n"
        "    });\n"
        "}\n"
        "\n"
        "// --- Switch Persona ---\n"
        "function switchPersonaTo(name) {\n"
        "    S.persona = name;\n"
        "    var sel = document.getElementById('persona-select');\n"
        "    if (sel) {\n"
        "        sel.value = name;\n"
        "        sel.dispatchEvent(new Event('change', {bubbles: true}));\n"
        "    }\n"
        "    loadPersonas();\n"
        "    toast('Switched to persona: ' + name, 'success');\n"
        "}\n"
    )
