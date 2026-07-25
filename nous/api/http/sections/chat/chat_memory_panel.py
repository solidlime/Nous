"""Chat memory panel — retrieved memories, saved memories, reflection, goals, equipment."""


def render_chat_memory_panel() -> str:
    """Return the memory activity panel HTML."""
    return """<!-- Memory activity panel (left) -->
                <div id="memory-panel">
                    <div class="memory-panel-title"><i data-lucide="brain"></i> 記憶活動</div>

                    <!-- Retrieved memories -->
                    <div class="memory-panel-section">
                        <div class="memory-section-header"><i data-lucide="download"></i> 取得された記憶</div>
                        <div id="memory-retrieved-list">
                            <div class="memory-empty">チャット中に自動更新されます</div>
                        </div>
                    </div>

                    <!-- Saved memories -->
                    <div class="memory-panel-section">
                        <div class="memory-section-header"><i data-lucide="save"></i> 保存された記憶</div>
                        <div id="memory-saved-list">
                            <div class="memory-empty">チャット中に自動更新されます</div>
                        </div>
                    </div>

                    <!-- Reflection -->
                    <div class="memory-panel-section">
                        <div class="memory-section-header" id="reflection-header"><i data-lucide="sparkles"></i> リフレクション</div>
                        <div id="memory-reflection-list">
                            <div class="memory-empty">リフレクション洞察がここに表示されます</div>
                        </div>
                    </div>

                    <!-- Active goals -->
                    <div class="memory-panel-section">
                        <div class="memory-section-header"><i data-lucide="target"></i> アクティブな目標</div>
                        <div id="memory-goals-list">
                            <div class="memory-empty">チャット中に自動更新されます</div>
                        </div>
                    </div>

                    <!-- Equipment -->
                    <div class="memory-panel-section">
                        <div class="memory-section-header"><i data-lucide="backpack"></i> 装備</div>
                        <div id="memory-equipment-list" style="max-height:150px;overflow-y:auto;">
                            <div class="memory-empty">会話中に装備変更があればここに表示されます</div>
                        </div>
                    </div>
                </div>"""
