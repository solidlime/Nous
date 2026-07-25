"""Chat settings sidebar — provider, MCP, TTS, image gen, context, and other settings."""

import sys

from .chat_sidebar_core import _render_context_section, _render_core_section, _render_sidebar_header
from .chat_sidebar_media import _render_image_section, _render_voice_section
from .chat_sidebar_memory import (
    _render_forgetting_section,
    _render_memory_enrichment_section,
    _render_memory_section,
    _render_mental_section,
    _render_reflection_section,
    _render_weights_section,
)
from .chat_sidebar_tools import _render_auto_capture_section, _render_mcp_section, _render_skills_section


def _render_debug_section() -> str:
    """Debug mode toggle."""
    return """
                        <!-- Debug & Other -->
                        <details data-category="other">
                            <summary><i data-lucide="bug"></i> デバッグ・その他 <span class="chat-help-icon" onmouseenter="N.Chat.core.showHelp(event, 'other')" title="説明を表示" onmouseleave="N.Chat.core.hideHelp()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-debug-mode"
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-debug-mode" class="chat-field-label" style="margin:0;cursor:pointer;"><i data-lucide="bug"></i> デバッグモード</label>
                                </div>
                            </div>
                        </details>"""


def _render_memorag_section() -> str:
    """MemoRAG settings — chunk size, overlap, top-k, similarity threshold."""
    return """
                        <!-- MemoRAG (moved from Settings) -->
                        <details data-category="memorag">
                            <summary><i data-lucide="search"></i> MemoRAG</summary>
                            <div class="details-body">
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-memorag-enabled"
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-memorag-enabled" class="chat-field-label" style="margin:0;cursor:pointer;">MemoRAG有効</label>
                                </div>
                                <div>
                                    <div class="chat-field-label">チャンクサイズ</div>
                                    <input type="number" id="chat-memorag-chunk-size" class="chat-field-input" min="64" step="1" value="512" />
                                </div>
                                <div>
                                    <div class="chat-field-label">チャンクオーバーラップ</div>
                                    <input type="number" id="chat-memorag-chunk-overlap" class="chat-field-input" min="0" step="1" value="64" />
                                </div>
                                <div>
                                    <div class="chat-field-label">Top-K</div>
                                    <input type="number" id="chat-memorag-top-k" class="chat-field-input" min="1" max="50" step="1" value="5" />
                                </div>
                                <div>
                                    <div style="display:flex;justify-content:space-between;">
                                        <span class="chat-field-label">類似度閾値</span>
                                        <span id="chat-memorag-similarity-threshold-val" style="font-size:0.72rem;color:var(--accent-purple);">0.70</span>
                                    </div>
                                    <input type="range" id="chat-memorag-similarity-threshold" class="chat-field-input" min="0" max="1" step="0.05" value="0.7"
                                        oninput="document.getElementById('chat-memorag-similarity-threshold-val').textContent=parseFloat(this.value).toFixed(2)"
                                        style="width:100%;accent-color:var(--accent-purple);" />
                                </div>
                                <div>
                                    <div class="chat-field-label">スナップショット間隔（時間）</div>
                                    <input type="number" id="chat-memorag-snapshot-interval-hours" class="chat-field-input" min="1" step="1" value="24" />
                                </div>
                            </div>
                        </details>"""


def _render_sidebar_footer() -> str:
    """Sticky footer buttons and settings-panel closing div."""
    return """
                    </div>
                    <!-- Sticky footer buttons -->
                    <div class="settings-footer">
                        <button class="chat-save-btn" onclick="N.Chat.settings.save()" aria-label="チャット設定を保存"><i data-lucide="save"></i> 設定を保存</button>
                        <button class="chat-clear-btn" onclick="N.Chat.history.clear()" aria-label="会話履歴をリセット"><i data-lucide="trash-2"></i> 会話をリセット</button>
                        <div id="chat-config-status" style="font-size:0.75rem; text-align:center; min-height:16px;"></div>
                    </div>
                </div>"""


def render_chat_sidebar() -> str:
    """Return the settings sidebar HTML with all configuration panels."""
    return "".join([
        _render_sidebar_header(),
        _render_core_section(),
        _render_context_section(),
        _render_memory_section(),
        _render_mcp_section(sys.executable),
        _render_skills_section(),
        _render_reflection_section(),
        _render_mental_section(),
        _render_weights_section(),
        _render_image_section(),
        _render_voice_section(),
        _render_debug_section(),
        _render_auto_capture_section(),
        _render_memory_enrichment_section(),
        _render_forgetting_section(),
        _render_memorag_section(),
        _render_sidebar_footer(),
    ])
