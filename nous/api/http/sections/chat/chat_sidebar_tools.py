"""Tool settings — MCP servers, skills, auto-capture."""


def _render_mcp_section(sys_executable: str) -> str:
    """MCP server config — server list, JSON editor, tool result limit."""
    return f"""
                        <!-- MCP Servers -->
                        <details data-category="tools">
                            <summary><i data-lucide="battery-charging"></i> MCPサーバー <span class="chat-help-icon" data-category="tools" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body" id="chat-mcp-section">
                                <div id="chat-mcp-server-list" style="display:flex;flex-direction:column;gap:2px;margin-bottom:8px;"></div>
                                <div>
                                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                                        <div style="font-size:0.72rem;color:var(--text-muted);">Claude の mcp.json 形式で貼り付け・編集できます</div>
                                        <button type="button" id="chat-mcp-format-btn" class="mem-action-btn" style="font-size:0.65rem;padding:2px 8px;" data-action="chat-format-mcp" title="JSONを整形">整形</button>
                                    </div>
                                    <textarea id="chat-mcp-json" class="chat-field-input" rows="6"
                                        style="resize:vertical;min-height:100px;font-family:monospace;font-size:0.73rem;line-height:1.45;"
                                        placeholder='[{{&#10;  "name": "memory-mcp",&#10;  "command": "{sys_executable}",&#10;  "args": ["-m", "nous.main"],&#10;  "env": {{}}&#10;}}]'></textarea>
                                    <div id="chat-mcp-json-error" style="font-size:0.72rem;color:var(--accent-red);margin-top:3px;display:none;"></div>
                                </div>
                                <div>
                                    <div class="chat-field-label chat-field-label-row">
                                        <span>ツール結果最大文字数</span>
                                        <span id="chat-tool-max-val" class="chat-field-value">4000</span>
                                    </div>
                                    <input type="range" id="chat-tool-result-max" class="chat-field-input" min="500" max="100000" step="500" value="4000"
                                        data-mirror="chat-tool-max-val" data-mirror-format="raw" />
                                </div>
                                <div class="chat-check-row">
                                    <input type="checkbox" id="chat-dynamic-tool-selection" checked />
                                    <label for="chat-dynamic-tool-selection">動的ツール選択</label>
                                </div>
                            </div>
                        </details>"""


def _render_skills_section() -> str:
    """Skills list container."""
    return """
                        <!-- Skills -->
                        <details data-category="skills">
                            <summary><i data-lucide="target"></i> Skills <span class="chat-help-icon" data-category="skills" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body" id="chat-skills-section">
                                <div id="chat-skills-list" style="display:flex;flex-direction:column;gap:4px;"></div>
                            </div>
                        </details>"""


def _render_auto_capture_section() -> str:
    """Auto-capture settings — nested child of the 記憶・抽出 group."""
    return """
                                <!-- Auto-capture (child of memory group, moved from Settings) -->
                                <details class="chat-subsection" data-category="auto_capture">
                                    <summary>自動キャプチャ <span class="chat-help-icon" data-category="auto_capture" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
                                    <div class="details-body">
                                        <div class="chat-check-row">
                                            <input type="checkbox" id="chat-auto-capture-enabled" />
                                            <label for="chat-auto-capture-enabled">自動キャプチャ有効</label>
                                        </div>
                                        <div>
                                            <div class="chat-field-label">実行間隔（秒）</div>
                                            <input type="number" id="chat-auto-capture-interval" class="chat-field-input" min="60" step="1" value="300" />
                                        </div>
                                        <div>
                                            <div class="chat-field-label">最大メモリ数</div>
                                            <input type="number" id="chat-auto-capture-max-memories" class="chat-field-input" min="1" max="50" step="1" value="10" />
                                        </div>
                                    </div>
                                </details>"""
