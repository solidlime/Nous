"""Wiki tab section: 記憶 wiki の閲覧（一覧 + 本文）。

読み取り専用ビュー。編纂サイクルの起動は API（plugin key 必須）側の責務で、
ブラウザに鍵を置かないためここには置かない。JS は
``static/features/wiki.js``（render_head の <script> で読み込む）。
"""


def render_wiki_tab() -> str:
    """Return the Wiki tab HTML section (list pane + article pane)."""
    return """
        <!-- ========== WIKI TAB ========== -->
        <section id="tab-wiki" class="tab-panel" role="tabpanel">
            <div class="tab-head">
                <h2><span><i data-lucide="book-open"></i></span> Wiki</h2>
                <div style="display:flex;align-items:center;gap:8px;">
                <button id="wiki-btn-history" class="glass-btn" title="更新履歴と差分を見る"><i data-lucide="history"></i></button>
                <button id="wiki-btn-recompile" class="glass-btn" title="いま編纂を走らせる（手動トリガ）"><i data-lucide="sparkles"></i></button>
                <button id="wiki-btn-edit" class="glass-btn" title="このページを手で編集する"><i data-lucide="pencil"></i></button>
                <button id="wiki-btn-delete" class="glass-btn" title="このページを削除する（取り消せない）"><i data-lucide="trash-2"></i></button>
                <button id="wiki-btn-refresh" class="glass-btn" title="Reload wiki pages"><i data-lucide="refresh-cw"></i></button>
            </div>
            </div>
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <aside class="glass p-3" style="align-self:start;">
                    <div style="font-size:0.7rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--text-muted); padding:4px 8px 8px;">Pages</div>
                    <input id="wiki-search" type="search" placeholder="検索（題名 / 本文）" autocomplete="off" style="width:100%; margin-bottom:8px; padding:7px 10px; border-radius:10px; border:1px solid var(--glass-border); background:rgba(15,23,42,0.45); color:var(--text-primary); font-size:0.82rem;" />
                    <div id="wiki-list">
                        <div class="skeleton skeleton-text" style="width:80%;"></div>
                        <div class="skeleton skeleton-text" style="width:60%;"></div>
                    </div>
                </aside>
                <article class="glass p-6 lg:col-span-2" style="align-self:start;">
                    <div id="wiki-article-head"></div>
                    <div id="wiki-sub"></div>
                    <div id="wiki-history"></div>
                    <div id="wiki-article-body" style="margin-top:12px;">
                        <div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text" style="width:80%;"></div>
                    </div>
                </article>
            </div>
        </section>"""
