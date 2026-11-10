"""Wiki tab section: 記憶 wiki の閲覧（一覧 + 本文）。

読み取り専用ビュー。編纂サイクルの起動は API（plugin key 必須）側の責務で、
ブラウザに鍵を置かないためここには置かない。JS は
``static/features/wiki.js``（render_head の <script> で読み込む）。
"""


def render_wiki_tab() -> str:
    """Return the Wiki tab HTML section (list pane + article pane)."""
    return """
        <style>
        .wiki-item { display:flex; flex-direction:column; gap:2px; width:100%; text-align:left; padding:10px 12px; margin-bottom:6px; border-radius:10px; border:1px solid var(--glass-border); background:transparent; cursor:pointer; transition:background 0.15s, border-color 0.15s; }
        .wiki-item:hover { background:rgba(var(--accent-blue-rgb), 0.08); }
        .wiki-item.active { border-color:rgba(var(--accent-blue-rgb), 0.5); background:rgba(var(--accent-blue-rgb), 0.12); }
        .wiki-item-title { font-size:0.88rem; font-weight:600; color:var(--text-primary); }
        .wiki-item-meta { font-size:0.7rem; color:var(--text-muted); }
        #wiki-article-body { font-size:0.9rem; line-height:1.75; color:var(--text-primary); }
        #wiki-article-body h1, #wiki-article-body h2 { font-size:1.05rem; font-weight:700; margin:16px 0 8px; }
        #wiki-article-body h3 { font-size:0.95rem; font-weight:600; margin:12px 0 6px; }
        #wiki-article-body p { margin:6px 0; }
        #wiki-article-body ul, #wiki-article-body ol { margin:6px 0 6px 20px; }
        #wiki-article-body li { margin:2px 0; }
        #wiki-article-body code { font-size:0.82rem; padding:1px 5px; border-radius:4px; background:rgba(148,163,184,0.15); }
        #wiki-article-body pre { padding:10px 12px; border-radius:10px; overflow-x:auto; background:rgba(15,23,42,0.5); }
        #wiki-article-body a { color:var(--accent-blue); text-decoration:underline; text-underline-offset:2px; }
        #wiki-article-body blockquote { border-left:3px solid var(--glass-border); padding-left:10px; color:var(--text-muted); }
        #wiki-edit-body { width:100%; min-height:320px; font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:0.82rem; line-height:1.6; padding:10px 12px; border-radius:10px; border:1px solid var(--glass-border); background:rgba(15,23,42,0.45); color:var(--text-primary); resize:vertical; }
        #wiki-edit-title { width:100%; font-size:1rem; font-weight:600; padding:8px 10px; border-radius:10px; border:1px solid var(--glass-border); background:rgba(15,23,42,0.45); color:var(--text-primary); }
        .wiki-edit-actions { display:flex; gap:8px; margin-top:10px; }
        </style>
        <!-- ========== WIKI TAB ========== -->
        <section id="tab-wiki" class="tab-panel" role="tabpanel">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="book-open"></i></span> Wiki</h2>
                <div style="display:flex;align-items:center;gap:8px;">
                <button id="wiki-btn-edit" class="glass-btn" title="このページを手で編集する"><i data-lucide="pencil"></i></button>
                <button id="wiki-btn-delete" class="glass-btn" title="このページを削除する（取り消せない）"><i data-lucide="trash-2"></i></button>
                <button id="wiki-btn-refresh" class="glass-btn" title="Reload wiki pages"><i data-lucide="refresh-cw"></i></button>
            </div>
            </div>
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <aside class="glass p-3" style="align-self:start;">
                    <div style="font-size:0.7rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--text-muted); padding:4px 8px 8px;">Pages</div>
                    <div id="wiki-list">
                        <div class="skeleton skeleton-text" style="width:80%;"></div>
                        <div class="skeleton skeleton-text" style="width:60%;"></div>
                    </div>
                </aside>
                <article class="glass p-6 lg:col-span-2" style="align-self:start;">
                    <div id="wiki-article-head"></div>
                    <div id="wiki-article-body" style="margin-top:12px;">
                        <div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text" style="width:80%;"></div>
                    </div>
                </article>
            </div>
        </section>"""
