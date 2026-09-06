"""Import/Export tab section for the Nous Dashboard.

Provides drag-and-drop ZIP import and full data export
(ZIP archive or JSON) for Nous persona data.
"""


def render_import_export_tab() -> str:
    """Return the HTML for the Import/Export tab panel."""
    return """
        <!-- ========== IMPORT/EXPORT TAB ========== -->
        <!-- DEAD: unreachable — dashboard.py never renders this tab and tab_js is dropped, so no JS receiver exists. data-dead-* attrs are CSP-safe placeholders only. -->
        <section id="tab-import-export" class="tab-panel" role="tabpanel">
            <div style="margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="refresh-cw"></i></span> Import / Export</h2>
            </div>
          <div id="import-export-content">

            <!-- Conversation File Import Section -->
            <div class="glass p-6" style="margin-bottom:24px">
              <h3 style="font-size:1.2rem;font-weight:600;color:var(--text-primary);margin-bottom:8px"><i data-lucide="message-circle"></i> Conversation Import</h3>
              <p style="font-size:0.85rem;color:var(--text-muted);margin-bottom:16px">Import user messages from a conversation export file on the server. Supports Claude Code JSONL, Claude.ai JSON, ChatGPT JSON.</p>
              <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
                <input id="conv-import-path" type="text" class="glass-input" placeholder="/path/to/conversation.json" style="flex:1;min-width:280px;padding:8px 14px;font-size:0.88rem">
                <button data-dead-io="import-conversation" class="glass-btn" style="padding:8px 24px;white-space:nowrap"><i data-lucide="download"></i> Import</button>
              </div>
              <div id="conv-import-result" style="display:none;margin-top:8px;font-size:0.85rem;padding:10px 14px;border-radius:8px;background:rgba(255,255,255,0.04)"></div>
            </div>

            <!-- Import Section -->
            <div class="glass p-6" style="margin-bottom:24px">
              <h3 style="font-size:1.2rem;font-weight:600;color:var(--text-primary);margin-bottom:16px"><i data-lucide="download"></i> Import Data</h3>

              <!-- Drag & drop zone -->
              <div id="drop-zone" style="border:2px dashed var(--glass-border);border-radius:12px;padding:48px 24px;text-align:center;cursor:pointer;transition:all 0.3s">
                <div style="font-size:3rem;margin-bottom:12px"><i data-lucide="folder"></i></div>
                <p style="color:var(--text-muted)">Drag &amp; drop a ZIP file here, or click to select</p>
                <p style="font-size:0.85rem;color:var(--text-muted);opacity:0.6;margin-top:8px">Supports v1 and v2 Nous data formats</p>
                <input type="file" id="import-file" accept=".zip" style="display:none">
              </div>

              <!-- Progress bar (hidden by default) -->
              <div id="import-progress" style="display:none;margin-top:16px">
                <div style="width:100%;background:rgba(255,255,255,0.1);border-radius:9999px;height:8px;overflow:hidden">
                  <div id="import-progress-bar" style="background:linear-gradient(to right,#a855f7,#ec4899);height:8px;border-radius:9999px;transition:width 0.3s;width:0%"></div>
                </div>
                <p id="import-status" style="font-size:0.85rem;color:var(--text-muted);margin-top:8px">Importing...</p>
              </div>

              <!-- Results (hidden by default) -->
              <div id="import-results" style="display:none;margin-top:16px" class="glass p-4">
                <!-- dynamically populated -->
              </div>
            </div>

            <!-- Export Section -->
            <div class="glass p-6">
              <h3 style="font-size:1.2rem;font-weight:600;color:var(--text-primary);margin-bottom:16px"><i data-lucide="upload"></i> Export Data</h3>
              <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
                <select id="export-format" class="glass-input" style="padding:8px 16px;min-width:180px">
                  <option value="zip">ZIP Archive (full backup)</option>
                  <option value="json">JSON (memories only)</option>
                </select>
                <button data-dead-io="export-data" class="glass-btn" style="padding:8px 24px"><i data-lucide="download"></i> Download</button>
              </div>
              <div id="export-preview" style="margin-top:16px;font-size:0.85rem;color:var(--text-muted)">
                Loading export info...
              </div>
            </div>

          </div>
        </section>"""


def render_import_export_js() -> str:
    """Return the JavaScript for the Import/Export tab.

    Handles drag-and-drop import, progress indication,
    export (ZIP / JSON), and export preview loading.
    """
    return r"""
// === Import/Export Tab ===

async function loadImportExport() {
    loadExportPreview();
}

// --- Conversation File Import ---
async function importConversation() {
    var filePath = (document.getElementById('conv-import-path').value || '').trim();
    var resultEl = document.getElementById('conv-import-result');
    if (!filePath) { toast('File path is required', 'error'); return; }
    resultEl.style.display = 'block';
    resultEl.style.color = 'var(--text-muted)';
    resultEl.textContent = 'Importing...';
    try {
        var resp = await api('/api/import-conversation/' + encodeURIComponent(S.persona), {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({file_path: filePath})
        });
        resultEl.style.color = 'var(--accent-green)';
        resultEl.textContent = '<i data-lucide="check-circle"></i> Imported ' + (resp.imported || 0) + ' messages' + (resp.skipped ? ' (' + resp.skipped + ' skipped)' : '') + '.';
        toast('Conversation imported successfully', 'success');
    } catch (e) {
        resultEl.style.color = 'var(--accent-red)';
        resultEl.textContent = '<i data-lucide="x-circle"></i> ' + (e.message || 'Import failed');
    }
}

// --- Drag & Drop ---
(function initDropZone() {
    document.addEventListener('DOMContentLoaded', function() {
        var dz = document.getElementById('drop-zone');
        var fi = document.getElementById('import-file');
        if (!dz || !fi) return;

        dz.addEventListener('click', function() { fi.click(); });
        fi.addEventListener('change', function(e) {
            if (e.target.files[0]) importData(e.target.files[0]);
        });

        dz.addEventListener('dragover', function(e) {
            e.preventDefault();
            dz.style.borderColor = 'var(--accent-purple)';
            dz.style.background = 'rgba(168,85,247,0.1)';
        });
        dz.addEventListener('dragleave', function(e) {
            e.preventDefault();
            dz.style.borderColor = 'var(--glass-border)';
            dz.style.background = '';
        });
        dz.addEventListener('drop', function(e) {
            e.preventDefault();
            dz.style.borderColor = 'var(--glass-border)';
            dz.style.background = '';
            var file = e.dataTransfer.files[0];
            if (file && file.name.endsWith('.zip')) {
                importData(file);
            } else {
                toast('Please drop a .zip file', 'error');
            }
        });
    });
})();

// --- Import ---
async function importData(file) {
    var progress = document.getElementById('import-progress');
    var bar = document.getElementById('import-progress-bar');
    var status = document.getElementById('import-status');
    var results = document.getElementById('import-results');

    // Reset & show progress
    progress.style.display = 'block';
    results.style.display = 'none';
    bar.style.width = '0%';
    bar.style.background = 'linear-gradient(to right,#a855f7,#ec4899)';
    status.textContent = 'Uploading...';

    // Simulate progress
    var pct = 0;
    var interval = setInterval(function() {
        pct = Math.min(pct + Math.random() * 15, 90);
        bar.style.width = pct + '%';
    }, 300);

    try {
        var fd = new FormData();
        fd.append('file', file);
        status.textContent = 'Importing ' + esc(file.name) + '...';

        var resp = await fetch('/api/import/' + encodeURIComponent(S.persona), {
            method: 'POST',
            body: fd
        });
        clearInterval(interval);

        if (!resp.ok) {
            var errBody = await resp.json().catch(function() { return {}; });
            throw new Error(errBody.detail || errBody.error || 'Import failed');
        }

        var data = await resp.json();
        bar.style.width = '100%';
        status.textContent = 'Import complete!';

        // Show results
        var imp = data.imported || {};
        var cards = Object.keys(imp).map(function(k) {
            return '<div class="glass p-3" style="text-align:center;border-radius:8px">'
                + '<div style="font-size:1.5rem;font-weight:700;color:var(--accent-purple)">' + esc(String(imp[k])) + '</div>'
                + '<div style="font-size:0.8rem;color:var(--text-muted)">' + esc(k) + '</div>'
                + '</div>';
        }).join('');

        results.style.display = 'block';
        safeSetHTML(results,
            '<div style="color:var(--text-primary);font-weight:600;margin-bottom:8px">\u2705 Import Successful</div>'
            + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px">'
            + cards
            + '</div>';

        toast('Import completed successfully!', 'success');
        loadExportPreview();
    } catch (e) {
        clearInterval(interval);
        bar.style.width = '100%';
        bar.style.background = 'linear-gradient(to right,#ef4444,#dc2626)';
        status.textContent = 'Import failed: ' + e.message;
        toast('Import failed: ' + e.message, 'error');
    }

    // Reset file input
    document.getElementById('import-file').value = '';
}

// --- Export ---
async function exportData() {
    var fmt = document.getElementById('export-format').value;
    if (!S.persona) { toast('No persona selected', 'error'); return; }

    try {
        toast('Preparing export...', 'info');

        if (fmt === 'zip') {
            var url = '/api/export/' + encodeURIComponent(S.persona);
            var a = document.createElement('a');
            a.href = url;
            a.download = S.persona + '_export.zip';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            toast('Download started!', 'success');
        } else {
            var data = await api('/api/dashboard/' + encodeURIComponent(S.persona));
            var blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
            var blobUrl = URL.createObjectURL(blob);
            var a2 = document.createElement('a');
            a2.href = blobUrl;
            a2.download = S.persona + '_memories.json';
            document.body.appendChild(a2);
            a2.click();
            document.body.removeChild(a2);
            URL.revokeObjectURL(blobUrl);
            toast('JSON export downloaded!', 'success');
        }
    } catch (e) {
        toast('Export failed: ' + e.message, 'error');
    }
}

// --- Export Preview ---
async function loadExportPreview() {
    var el = document.getElementById('export-preview');
    if (!el || !S.persona) return;

    try {
        var data = await api('/api/dashboard/' + encodeURIComponent(S.persona));
        var stats = data.stats || {};
        var items = data.items || [];
        var equip = data.equipment || {};
        var equipCount = Object.values(equip).filter(function(v) { return v; }).length;

        safeSetHTML(el,
            '<div style="display:flex;gap:16px;flex-wrap:wrap">'
            + '<span>\uD83D\uDCDD <strong>' + (stats.total_count || 0) + '</strong> memories</span>'
            + '<span>\uD83C\uDF92 <strong>' + items.length + '</strong> items</span>'
            + '<span>\u2694\uFE0F <strong>' + equipCount + '</strong> equipped slots</span>'
            + '</div>';
    } catch (e) {
        safeSetHTML(el, '<span style="color:#ef4444">Failed to load preview</span>');
    }
}
"""
