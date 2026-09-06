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
                                <div class="chat-check-row">
                                    <input type="checkbox" id="chat-debug-mode" />
                                    <label for="chat-debug-mode"><i data-lucide="bug"></i> デバッグモード</label>
                                </div>
                            </div>
                        </details>"""


def _render_sidebar_footer() -> str:
    """Sticky footer buttons and settings-panel closing div."""
    return """
                    </div>
                    <!-- Sticky footer buttons -->
                    <div class="settings-footer">
                        <button class="chat-save-btn" data-action="chat-save" aria-label="チャット設定を保存"><i data-lucide="save"></i> 設定を保存</button>
                        <button class="chat-clear-btn" data-action="chat-clear" aria-label="会話履歴をリセット"><i data-lucide="trash-2"></i> 会話をリセット</button>
                        <div id="chat-config-status" style="font-size:0.75rem; text-align:center; min-height:16px;"></div>
                    </div>
                </div>"""


def render_chat_sidebar() -> str:
    """Return the settings sidebar HTML with all configuration panels.

    Section order is grouped by mental model:
      1. connection & generation (core, context)
      2. memory family (extraction, reflection, mental model, auto-capture,
         enrichment, forgetting, retrieval weights)
      3. external tools (MCP, skills)
      4. media output (image, voice)
      5. everything else (debug) — always last
    """
    return "".join(
        [
            _render_sidebar_header(),
            _render_core_section(),
            _render_context_section(),
            _render_memory_section(),
            _render_reflection_section(),
            _render_mental_section(),
            _render_auto_capture_section(),
            _render_memory_enrichment_section(),
            _render_forgetting_section(),
            _render_weights_section(),
            _render_mcp_section(sys.executable),
            _render_skills_section(),
            _render_image_section(),
            _render_voice_section(),
            _render_debug_section(),
            _render_sidebar_footer(),
        ]
    )
