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
                            <summary><i data-lucide="bug"></i> デバッグ・その他 <span class="chat-help-icon" data-category="other" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-debug-mode"
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-debug-mode" class="chat-field-label" style="margin:0;cursor:pointer;"><i data-lucide="bug"></i> デバッグモード</label>
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
    return "".join(
        [
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
            _render_sidebar_footer(),
        ]
    )
