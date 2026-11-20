"""Memories tab section: HTML skeleton and JavaScript for full CRUD, advanced search, sorting, and batch operations."""


def render_memories_tab() -> str:
    """Return the memories tab HTML section with all UI elements."""
    return """        <!-- ========== MEMORIES TAB ========== -->
        <section id="tab-memories" class="tab-panel" role="tabpanel">
            <div class="tab-head">
                <h2><span><i data-lucide="brain"></i></span> Memories</h2>
            </div>

            <div id="memories-content">
                <div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text" style="width:80%"></div></div>
            </div>

            <!-- Edit/Create Modal -->
            <div id="mem-edit-overlay" class="mem-edit-overlay" data-action="mem-edit-backdrop">
                <div class="mem-edit-modal">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
                        <h3 id="edit-modal-title" style="font-size:1.1rem;font-weight:700;color:var(--text-primary)">Edit Memory</h3>
                        <button class="mem-modal-close" data-action="mem-edit-close">&#10005;</button>
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
                            <option value="joy">Joy</option>
                            <option value="sadness">Sadness</option>
                            <option value="anger">Anger</option>
                            <option value="fear">Fear</option>
                            <option value="surprise">Surprise</option>
                            <option value="disgust">&#129326; Disgust</option>
                            <option value="love">&#10084; Love</option>
                            <option value="neutral">Neutral</option>
                            <option value="anticipation">&#129300; Anticipation</option>
                            <option value="trust">&#129309; Trust</option>
                            <option value="anxiety">Anxiety</option>
                            <option value="excitement">&#127881; Excitement</option>
                            <option value="frustration">Frustration</option>
                            <option value="nostalgia">&#127749; Nostalgia</option>
                            <option value="pride">&#129412; Pride</option>
                            <option value="shame">Shame</option>
                            <option value="guilt">Guilt</option>
                            <option value="loneliness">&#128148; Loneliness</option>
                            <option value="contentment">Contentment</option>
                            <option value="curiosity">Curiosity</option>
                            <option value="awe">Awe</option>
                            <option value="relief">Relief</option>
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
                        <button class="glass-btn" data-action="mem-edit-close">Cancel</button>
                        <button class="glass-btn glass-btn-success" data-action="mem-edit-save"><i data-lucide="save"></i> Save</button>
                    </div>
                </div>
            </div>
        </section>"""
