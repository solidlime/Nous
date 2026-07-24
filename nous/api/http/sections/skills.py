"""Skills management tab for the Nous Dashboard."""

from __future__ import annotations


def render_skills_tab() -> str:
    return """
        <section id="tab-skills" class="tab-panel" role="tabpanel">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="target"></i></span> Skills</h2>
                <div style="display:flex;gap:8px;">
                    <button onclick="syncSkillsFromFiles()" title="data/skills/<name>/SKILL.md をDBに同期" style="padding:6px 14px;border-radius:8px;background:rgba(52,211,153,0.1);border:1px solid rgba(52,211,153,0.25);color:var(--accent-green);font-size:0.82rem;cursor:pointer;font-weight:600;"><i data-lucide="folder-open"></i> ファイルから同期</button>
                    <button onclick="showSkillForm()" style="padding:6px 16px;border-radius:8px;background:var(--accent-blue);border:none;color:white;font-size:0.85rem;cursor:pointer;font-weight:600;">+ 新規スキル</button>
                </div>
            </div>
            <div id="skill-form-area" style="display:none;margin-bottom:16px;" class="glass" style="padding:16px;">
                <div style="padding:16px;display:flex;flex-direction:column;gap:10px;">
                    <div style="font-size:0.85rem;font-weight:600;color:var(--text-primary);" id="skill-form-title">新規スキル作成</div>
                    <input type="hidden" id="skill-edit-id" value="" />
                    <div>
                        <div class="chat-field-label">スキル名</div>
                        <input type="text" id="skill-name" style="width:100%;background:rgba(255,255,255,0.06);border:1px solid var(--glass-border);border-radius:8px;padding:8px 10px;color:var(--text-primary);font-size:0.85rem;outline:none;" placeholder="例: code_reviewer" />
                    </div>
                    <div>
                        <div class="chat-field-label">説明</div>
                        <input type="text" id="skill-description" style="width:100%;background:rgba(255,255,255,0.06);border:1px solid var(--glass-border);border-radius:8px;padding:8px 10px;color:var(--text-primary);font-size:0.85rem;outline:none;" placeholder="スキルの簡潔な説明" />
                    </div>
                    <div style="display:flex;gap:8px;">
                        <button onclick="saveSkill()" style="padding:7px 20px;border-radius:8px;background:var(--accent-blue);border:none;color:white;font-size:0.85rem;cursor:pointer;font-weight:600;">保存</button>
                        <button onclick="hideSkillForm()" style="padding:7px 16px;border-radius:8px;background:rgba(255,255,255,0.06);border:1px solid var(--glass-border);color:var(--text-secondary);font-size:0.85rem;cursor:pointer;">キャンセル</button>
                    </div>
                </div>
            </div>
            <div id="skills-table-area" class="glass table-responsive-wrap" style="padding:0;overflow:hidden;">
                <table class="table-card-mobile" style="width:100%;border-collapse:collapse;">
                    <thead>
                        <tr style="border-bottom:1px solid var(--glass-border);">
                            <th style="padding:10px 16px;text-align:left;font-size:0.8rem;color:var(--text-muted);font-weight:600;" data-label="名前">名前</th>
                            <th style="padding:10px 16px;text-align:left;font-size:0.8rem;color:var(--text-muted);font-weight:600;" data-label="説明">説明</th>
                            <th style="padding:10px 16px;text-align:right;font-size:0.8rem;color:var(--text-muted);font-weight:600;" data-label="操作">操作</th>
                        </tr>
                    </thead>
                    <tbody id="skills-tbody"></tbody>
                </table>
                <div id="skills-empty" style="padding:40px;text-align:center;color:var(--text-muted);font-size:0.9rem;">スキルがありません。「+ 新規スキル」から追加してください。</div>
            </div>
        </section>
    """


def render_skills_js() -> str:
    return r"""
/* =================================================================
   SKILLS TAB
   ================================================================= */

function loadSkills() {
    loadSkillsList();
}

async function loadSkillsList() {
    try {
        const skills = await api('/api/skills');
        renderSkillsTable(skills);
    } catch (e) {
        document.getElementById('skills-empty').textContent = '読込失敗: ' + e.message;
    }
}

function renderSkillsTable(skills) {
    const tbody = document.getElementById('skills-tbody');
    const empty = document.getElementById('skills-empty');
    if (!tbody) return;
    tbody.textContent = '';
    if (!skills || skills.length === 0) {
        if (empty) empty.style.display = 'block';
        return;
    }
    if (empty) empty.style.display = 'none';
    skills.forEach(skill => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid var(--glass-border)';
        safeSetHTML(tr, `
            <td style="padding:10px 16px;font-size:0.85rem;color:var(--text-primary);font-weight:500;" data-label="名前">${esc(skill.name)}</td>
            <td style="padding:10px 16px;font-size:0.82rem;color:var(--text-secondary);" data-label="説明">${esc(skill.description || '')}</td>
            <td style="padding:10px 16px;text-align:right;display:flex;gap:6px;justify-content:flex-end;" data-label="操作">
                <button onclick="editSkill(${JSON.stringify(JSON.stringify(skill))})" style="padding:4px 12px;border-radius:6px;background:rgba(96,165,250,0.1);border:1px solid rgba(96,165,250,0.2);color:var(--accent-blue);font-size:0.78rem;cursor:pointer;min-height:44px;min-width:44px;">編集</button>
                <button onclick="deleteSkill('${esc(skill.name)}')" style="padding:4px 12px;border-radius:6px;background:rgba(248,113,113,0.08);border:1px solid rgba(248,113,113,0.2);color:var(--accent-red);font-size:0.78rem;cursor:pointer;min-height:44px;min-width:44px;">削除</button>
            </td>`;
        tbody.appendChild(tr);
    });
}

function showSkillForm() {
    document.getElementById('skill-form-title').textContent = '新規スキル作成';
    document.getElementById('skill-edit-id').value = '';
    document.getElementById('skill-name').value = '';
    document.getElementById('skill-description').value = '';
    document.getElementById('skill-name').disabled = false;
    document.getElementById('skill-form-area').style.display = 'block';
}

function hideSkillForm() {
    document.getElementById('skill-form-area').style.display = 'none';
}

function editSkill(skillJson) {
    const skill = JSON.parse(skillJson);
    document.getElementById('skill-form-title').textContent = 'スキル編集: ' + skill.name;
    document.getElementById('skill-edit-id').value = skill.name;
    document.getElementById('skill-name').value = skill.name;
    document.getElementById('skill-name').disabled = true;
    document.getElementById('skill-description').value = skill.description || '';
    document.getElementById('skill-form-area').style.display = 'block';
}

async function saveSkill() {
    const editId = document.getElementById('skill-edit-id').value;
    const name = document.getElementById('skill-name').value.trim();
    const description = document.getElementById('skill-description').value.trim();
    if (!name) { toast('スキル名を入力してください', 'error'); return; }
    try {
        if (editId) {
            await api('/api/skills/' + encodeURIComponent(editId), { method: 'PUT', body: JSON.stringify({ description }) });
        } else {
            await api('/api/skills', { method: 'POST', body: JSON.stringify({ name, description }) });
        }
        hideSkillForm();
        loadSkillsList();
        toast('スキルを保存しました', 'success');
    } catch (e) {
        toast('保存失敗: ' + e.message, 'error');
    }
}

async function deleteSkill(name) {
    if (!confirm('スキル「' + name + '」を削除しますか？')) return;
    try {
        await api('/api/skills/' + encodeURIComponent(name), { method: 'DELETE' });
        loadSkillsList();
        toast('削除しました', 'success');
    } catch (e) {
        toast('削除失敗: ' + e.message, 'error');
    }
}

async function syncSkillsFromFiles() {
    try {
        const result = await api('/api/skills/sync', { method: 'POST' });
        loadSkillsList();
        toast(`${result.synced}件のスキルを同期しました`, 'success');
    } catch (e) {
        toast('同期失敗: ' + e.message, 'error');
    }
}
"""
