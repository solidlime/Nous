"""Memories tab section: HTML skeleton and JavaScript for full CRUD, advanced search, sorting, and batch operations."""

from pathlib import Path

_JS_DIR = Path(__file__).resolve().parent.parent / "static" / "features" / "memories"
_JS = "".join(
    (_JS_DIR / f).read_text(encoding="utf-8")
    for f in ["memories-core.js", "memories-list.js", "memories-search.js", "memories-edit.js"]
)


def render_memories_tab() -> str:
    """Return the memories tab HTML section with all UI elements."""
    return """        <!-- ========== MEMORIES TAB ========== -->
        <section id="tab-memories" class="tab-panel" role="tabpanel">
            <div style="margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="brain"></i></span> Memories</h2>
            </div>
            <style>
            /* ── Tag chips with per-tag hue ── */
            .mem-tag-chip {
                display: inline-flex; align-items: center; gap: 3px;
                padding: 2px 10px; border-radius: 20px; font-size: 0.72rem; font-weight: 600;
                background: hsla(var(--chip-hue), 70%, 60%, 0.15);
                color: hsla(var(--chip-hue), 70%, 70%, 1);
                border: 1px solid hsla(var(--chip-hue), 70%, 60%, 0.3);
            }
            html.light .mem-tag-chip { color: hsla(var(--chip-hue), 70%, 35%, 1); }

            /* ── Advanced search panel ── */
            .adv-search-panel {
                max-height: 0; overflow: hidden;
                transition: max-height 0.35s ease, padding 0.35s ease, opacity 0.35s ease;
                opacity: 0; padding: 0 16px;
            }
            .adv-search-panel.open { max-height: 600px; opacity: 1; padding: 16px; }
            .adv-search-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
            .adv-search-label { font-size: 0.78rem; color: var(--text-muted); min-width: 80px; }

            /* ── Search mode button group ── */
            .mode-btn-group {
                display: flex; gap: 2px; border-radius: 10px; overflow: hidden;
                border: 1px solid var(--glass-border);
            }
            .mode-btn {
                padding: 5px 12px; font-size: 0.75rem; border: none; background: transparent;
                color: var(--text-muted); cursor: pointer; transition: all 0.2s;
            }
            .mode-btn.active {
                background: rgba(var(--accent-blue-rgb), 0.25); color: var(--accent-blue); font-weight: 600;
            }

            /* ── Toolbar ── */
            .mem-toolbar {
                display: flex; gap: 8px; flex-wrap: wrap; align-items: center; padding: 10px 0;
            }
            .mem-toolbar-spacer { flex: 1; }

            /* ── Batch bar ── */
            .mem-batch-bar {
                display: none; gap: 8px; align-items: center; padding: 10px 16px;
                background: rgba(248,113,113,0.08); border-radius: 10px; margin-bottom: 8px;
                border: 1px solid rgba(248,113,113,0.2);
            }
            .mem-batch-bar.active { display: flex; }

            /* ── View toggle ── */
            .view-toggle {
                display: flex; gap: 2px; border-radius: 8px; overflow: hidden;
                border: 1px solid var(--glass-border);
            }
            .view-btn {
                padding: 5px 10px; font-size: 0.8rem; border: none; background: transparent;
                color: var(--text-muted); cursor: pointer; transition: all 0.2s;
            }
            .view-btn.active { background: rgba(var(--accent-blue-rgb), 0.2); color: var(--accent-blue); }

            /* ── Compact list view ── */
            .memory-compact {
                display: flex; align-items: center; gap: 12px; padding: 8px 16px;
                border-bottom: 1px solid var(--glass-border); font-size: 0.82rem; cursor: pointer;
                transition: background 0.2s;
            }
            .memory-compact:hover { background: rgba(var(--accent-blue-rgb), 0.05); }
            .memory-compact:last-child { border-bottom: none; }
            .mem-compact-key {
                font-family: monospace; color: var(--accent-purple); font-size: 0.75rem;
                min-width: 120px; flex-shrink: 0; overflow: hidden;
                text-overflow: ellipsis; white-space: nowrap;
            }
            .mem-compact-content {
                flex: 1; color: var(--text-secondary); overflow: hidden;
                text-overflow: ellipsis; white-space: nowrap;
            }
            .mem-compact-meta { display: flex; gap: 6px; align-items: center; flex-shrink: 0; }
            .mem-compact-imp {
                width: 50px; height: 4px; border-radius: 2px;
                background: rgba(255,255,255,0.08); overflow: hidden;
            }
            .mem-compact-imp-fill {
                height: 100%; border-radius: 2px;
                background: linear-gradient(90deg, var(--accent-purple), var(--accent-pink));
            }

            /* ── Edit/Create modal overlay ── */
            .mem-edit-overlay {
                position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 1100;
                display: none; align-items: center; justify-content: center;
                padding: 20px; backdrop-filter: blur(4px);
            }
            .mem-edit-overlay.active { display: flex; }
            .mem-edit-modal {
                background: var(--bg-secondary); border: 1px solid var(--glass-border);
                border-radius: var(--card-radius); max-width: 640px; width: 100%;
                max-height: 85vh; overflow-y: auto; padding: 24px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.4);
                animation: fadeIn 0.2s ease;
            }
            @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
            .form-group { margin-bottom: 14px; }
            .form-label { display: block; font-size: 0.78rem; color: var(--text-muted); margin-bottom: 4px; font-weight: 600; }
            .form-textarea {
                width: 100%; min-height: 120px; background: rgba(255,255,255,0.06);
                border: 1px solid var(--glass-border); border-radius: 10px;
                color: var(--text-primary); padding: 10px; font-size: 0.88rem;
                font-family: inherit; resize: vertical; outline: none;
            }
            .form-textarea:focus { border-color: var(--accent-blue); box-shadow: 0 0 0 3px rgba(var(--accent-blue-rgb), 0.2); }
            html.light .form-textarea { background: rgba(139,92,246,0.06); }

            /* ── Tags input ── */
            .tags-input-wrap {
                display: flex; flex-wrap: wrap; gap: 4px; padding: 6px 10px; min-height: 38px; align-items: center;
                background: rgba(255,255,255,0.06); border: 1px solid var(--glass-border); border-radius: 10px;
            }
            .tags-input-wrap:focus-within { border-color: var(--accent-blue); box-shadow: 0 0 0 3px rgba(var(--accent-blue-rgb), 0.2); }
            html.light .tags-input-wrap { background: rgba(139,92,246,0.06); }
            .tag-chip-edit {
                display: inline-flex; align-items: center; gap: 3px; padding: 2px 8px;
                border-radius: 14px; font-size: 0.75rem; font-weight: 600;
                background: hsla(var(--chip-hue), 70%, 60%, 0.2); color: hsla(var(--chip-hue), 70%, 70%, 1);
                border: 1px solid hsla(var(--chip-hue), 70%, 60%, 0.3);
            }
            .tag-chip-remove { cursor: pointer; opacity: 0.6; font-size: 0.85rem; line-height: 1; }
            .tag-chip-remove:hover { opacity: 1; }
            .tag-text-input {
                border: none; background: transparent; color: var(--text-primary); font-size: 0.82rem;
                outline: none; min-width: 60px; flex: 1;
            }

            /* ── Range slider ── */
            .range-row { display: flex; align-items: center; gap: 8px; }
            .range-value { font-size: 0.78rem; color: var(--accent-purple); min-width: 32px; text-align: center; font-weight: 600; }
            input[type="range"].glass-range {
                -webkit-appearance: none; appearance: none; width: 100%; height: 6px; border-radius: 3px;
                background: rgba(255,255,255,0.1); outline: none;
            }
            input[type="range"].glass-range::-webkit-slider-thumb {
                -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%;
                background: var(--accent-purple); cursor: pointer; border: 2px solid var(--bg-secondary);
                box-shadow: 0 0 8px rgba(var(--accent-blue-rgb), 0.4);
            }
            input[type="range"].glass-range::-moz-range-thumb {
                width: 16px; height: 16px; border-radius: 50%; background: var(--accent-purple);
                cursor: pointer; border: 2px solid var(--bg-secondary);
            }

            /* ── Checkbox in select mode ── */
            .mem-cb { display: none; }
            .mem-cb.show { display: inline-block; }
            .mem-cb input[type="checkbox"] {
                width: 16px; height: 16px; accent-color: var(--accent-purple); cursor: pointer; vertical-align: middle;
            }

            /* ── Copy button ── */
            .copy-btn { background: none; border: none; cursor: pointer; padding: 2px 6px; font-size: 0.8rem; opacity: 0.5; transition: opacity 0.2s; color: var(--text-primary); }
            .copy-btn:hover { opacity: 1; }

            /* ── Progress bar in modal ── */
            .modal-progress { display: flex; align-items: center; gap: 8px; }
            .modal-progress-bar { flex: 1; height: 8px; border-radius: 4px; background: rgba(255,255,255,0.08); overflow: hidden; }
            .modal-progress-fill { height: 100%; border-radius: 4px; transition: width 0.3s ease; }

            /* ── Filter tag pills in advanced search ── */
            .filter-tags-wrap {
                display: flex; flex-wrap: wrap; gap: 4px; padding: 4px; min-height: 30px;
                background: rgba(255,255,255,0.04); border-radius: 8px;
            }
            .filter-tag {
                padding: 3px 10px; border-radius: 14px; font-size: 0.72rem; cursor: pointer;
                border: 1px solid var(--glass-border); color: var(--text-muted); transition: all 0.2s;
                user-select: none;
            }
            .filter-tag.active {
                background: rgba(var(--accent-blue-rgb), 0.2); color: var(--accent-blue);
                border-color: rgba(var(--accent-blue-rgb), 0.4);
            }

            /* ── Sort dropdown ── */
            .mem-sort-select { font-size: 0.8rem; padding: 5px 10px; }
            </style>

            <div id="memories-content">
                <div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text" style="width:80%"></div></div>
            </div>

            <!-- Edit/Create Modal -->
            <div id="mem-edit-overlay" class="mem-edit-overlay" onclick="if(event.target===this)closeEditModal()">
                <div class="mem-edit-modal">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
                        <h3 id="edit-modal-title" style="font-size:1.1rem;font-weight:700;color:var(--text-primary)">Edit Memory</h3>
                        <button class="mem-modal-close" onclick="closeEditModal()">&#10005;</button>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Content *</label>
                        <textarea id="edit-content" class="form-textarea" placeholder="Memory content..."></textarea>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Tags</label>
                        <div class="tags-input-wrap" id="edit-tags-wrap">
                            <input type="text" class="tag-text-input" id="edit-tag-input" placeholder="Type tag + Enter">
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Importance</label>
                        <div class="range-row">
                            <span class="range-value" id="edit-imp-val">0.50</span>
                            <input type="range" class="glass-range" id="edit-importance" min="0" max="1" step="0.01" value="0.5">
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Emotion Type</label>
                        <select id="edit-emotion" class="glass-input" style="width:100%">
                            <option value="">None</option>
                            <option value="joy"><i data-lucide="smile"></i> Joy</option>
                            <option value="sadness"><i data-lucide="frown"></i> Sadness</option>
                            <option value="anger"><i data-lucide="angry"></i> Anger</option>
                            <option value="fear"><i data-lucide="alert-triangle"></i> Fear</option>
                            <option value="surprise"><i data-lucide="alert-triangle"></i> Surprise</option>
                            <option value="disgust">&#129326; Disgust</option>
                            <option value="love">&#10084; Love</option>
                            <option value="neutral"><i data-lucide="meh"></i> Neutral</option>
                            <option value="anticipation">&#129300; Anticipation</option>
                            <option value="trust">&#129309; Trust</option>
                            <option value="anxiety"><i data-lucide="alert-triangle"></i> Anxiety</option>
                            <option value="excitement">&#127881; Excitement</option>
                            <option value="frustration"><i data-lucide="frown"></i> Frustration</option>
                            <option value="nostalgia">&#127749; Nostalgia</option>
                            <option value="pride">&#129412; Pride</option>
                            <option value="shame"><i data-lucide="frown"></i> Shame</option>
                            <option value="guilt"><i data-lucide="frown"></i> Guilt</option>
                            <option value="loneliness">&#128148; Loneliness</option>
                            <option value="contentment"><i data-lucide="smile"></i> Contentment</option>
                            <option value="curiosity"><i data-lucide="search-check"></i> Curiosity</option>
                            <option value="awe"><i data-lucide="frown"></i> Awe</option>
                            <option value="relief"><i data-lucide="smile-plus"></i> Relief</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Emotion Intensity</label>
                        <div class="range-row">
                            <span class="range-value" id="edit-emo-val">0.00</span>
                            <input type="range" class="glass-range" id="edit-emo-intensity" min="0" max="1" step="0.01" value="0">
                        </div>
                    </div>
                    <input type="hidden" id="edit-memory-key" value="">
                    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
                        <button class="glass-btn" onclick="closeEditModal()">Cancel</button>
                        <button class="glass-btn glass-btn-success" onclick="saveMemory()"><i data-lucide="save"></i> Save</button>
                    </div>
                </div>
            </div>
        </section>"""


def render_memories_js() -> str:
    """Return all JavaScript for the Memories tab."""
    return _JS
