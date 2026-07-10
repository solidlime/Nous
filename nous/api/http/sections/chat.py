"""Chat tab section for the Nous Dashboard.

Renders a fully-functional chat interface with SSE streaming,
tool call visualization, and an inline settings panel.
"""

import sys

from .coding_agent import render_coding_agent_panel


def render_chat_tab() -> str:
    """Return the HTML for the Chat tab."""
    return f"""
        <link rel="stylesheet" href="/static/chat.css">
        <!-- ========== CHAT TAB ========== -->
        <section id="tab-chat" class="tab-panel" role="tabpanel">
            <div style="position:relative; margin-bottom:16px; display:flex; align-items:center; justify-content:space-between; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="message-circle"></i></span> Chat</h2>
                <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
                    <button class="mem-panel-toggle" id="memory-panel-toggle-btn" onclick="toggleMemoryPanel()" title="記憶パネルを開閉" aria-label="記憶パネルの表示切替"><i data-lucide="brain"></i></button>
                    <button class="chat-sidebar-toggle" onclick="toggleSettingsPanel()" id="chat-sidebar-toggle-btn" title="設定パネルを開閉" aria-label="設定パネルの表示切替"><i data-lucide="settings"></i></button>
                </div>
            </div>
            <div id="chat-layout" class="glass" style="padding:0; overflow:hidden;">
                <!-- Mobile backdrop for settings panel -->
                <div id="settings-backdrop" onclick="toggleSettingsPanel()"></div>
                <!-- Memory activity panel (left) -->
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
                </div>

                <!-- Chat area -->
                <div id="chat-main">
                    <!-- Persona Portrait -->
                    <div id="portrait-area">
                        <div id="portrait-container" onclick="onPortraitClick()">
                            <div id="portrait-placeholder">
                                <i data-lucide="user"></i>
                            </div>
                            <img id="portrait-img" alt="Persona portrait" style="display:none;" />
                        </div>
                        <div id="portrait-status"></div>
                    </div>
                    <div id="chat-messages">
                        <div class="chat-welcome" id="chat-welcome">
                            <div class="chat-welcome-icon"><i data-lucide="message-circle"></i></div>
                            <p>チャットを開始するには下のテキストボックスにメッセージを入力してください。</p>
                            <p class="chat-welcome-hint">APIキーとプロバイダーを設定してください。<br><a href="#" onclick="toggleSettingsPanel();return false;" class="chat-welcome-link"><i data-lucide="settings"></i> 設定パネルを開く</a></p>
                            <div class="chat-welcome-commands">
                                <span class="chat-welcome-cmd">/memory</span>
                                <span class="chat-welcome-cmd">/goal</span>
                                <span class="chat-welcome-cmd">/code</span>
                                <span class="chat-welcome-cmd">/help</span>
                                <span class="chat-welcome-cmd">/search</span>
                                <span class="chat-welcome-cmd">/image</span>
                                <span class="chat-welcome-cmd">/sandbox</span>
                                <span class="chat-welcome-cmd">/invoke_skill</span>
                            </div>
                        </div>
                    </div>
                    <div id="chat-status"></div>
                    <div id="chat-attachments"></div>
                    <div id="chat-input-area">
                        <textarea id="chat-input" placeholder="メッセージを入力... (Enter で送信、Shift+Enter で改行)" rows="1" aria-label="チャットメッセージ入力"></textarea>
                        <div style="display:flex;align-items:center;gap:6px;">
                            <button id="chat-cancel-btn" class="chat-stop-btn" onclick="chatCancel()" style="display:none" aria-label="応答を停止"><i data-lucide="stop-circle"></i> 中止</button>
                            <button id="chat-voice-btn" class="chat-action-btn" onclick="toggleVoiceInput()" title="音声入力" aria-label="音声入力の切替"><i data-lucide="mic"></i></button>
                            <button id="chat-export-btn" class="chat-action-btn" onclick="exportChatHistory()" title="会話をエクスポート" aria-label="会話履歴をエクスポート"><i data-lucide="download"></i></button>
                            <button id="chat-send-btn" onclick="chatSend()" aria-label="メッセージを送信">送信</button>
                        </div>
                    </div>
                </div>
                <!-- Settings sidebar -->
                <div id="settings-panel" class="glass" style="margin:0; border-radius:0; border-left:1px solid var(--glass-border); padding:0;">
                    <!-- Mobile close button -->
                    <button id="settings-panel-close-btn" class="settings-panel-close" onclick="toggleSettingsPanel()" title="設定パネルを閉じる" aria-label="設定パネルを閉じる"><i data-lucide="x"></i></button>
                    <div class="settings-scroll-container">
                        <div style="position:sticky;top:0;z-index:10;background:var(--glass-bg);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);font-size:0.9rem;font-weight:600;color:var(--text-primary);padding:12px 0 8px;margin:0 -16px 8px;border-bottom:1px solid var(--glass-border);display:flex;align-items:center;gap:8px;box-shadow:0 2px 12px rgba(0,0,0,0.1);">
                            <span style="font-size:1.1rem;margin-left:16px;"><i data-lucide="settings"></i></span>
                            <span>チャット設定</span>
                        </div>
                        <!-- Provider / Model / API -->
                        <details data-category="core" open>
                            <summary><i data-lucide="wrench"></i> 基本設定 <span class="chat-help-icon" onmouseenter="showHelpTooltip(event, 'core')" title="説明を表示" onmouseleave="hideHelpTooltip()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div>
                                    <div class="chat-field-label">プロバイダー</div>
                                    <select id="chat-provider" class="chat-field-input" onchange="onChatProviderChange()">
                                        <option value="anthropic">Anthropic (Claude)</option>
                                        <option value="openai">OpenAI</option>
                                        <option value="openrouter">OpenRouter</option>
                                    </select>
                                </div>
                                <div>
                                    <div class="chat-field-label">モデル <span style="color:var(--accent-blue);font-size:0.7rem;">（空白でデフォルト）</span></div>
                                    <input type="text" id="chat-model" class="chat-field-input" placeholder="例: claude-opus-4-5" />
                                </div>
                                <div>
                                    <div class="chat-field-label">APIキー</div>
                                    <input type="password" id="chat-api-key" class="chat-field-input" placeholder="sk-..." autocomplete="off" />
                                </div>
                                <!-- 画像生成設定 -->
                                <div class="chat-config-section">
                                    <h4 style="font-size:0.82rem;font-weight:600;color:var(--text-secondary);margin:8px 0 4px;display:flex;align-items:center;gap:6px;"><i data-lucide="image"></i> 画像生成</h4>
                                    <div class="chat-config-row" style="display:flex;align-items:center;gap:8px;margin:4px 0;">
                                        <label class="chat-config-label" style="display:flex;align-items:center;gap:6px;font-size:0.8rem;color:var(--text-secondary);cursor:pointer;">
                                            <input type="checkbox" id="chat-image-gen-enabled" class="chat-config-checkbox" style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                            <span>画像生成を有効にする</span>
                                        </label>
                                    </div>
                                    <div id="chat-image-gen-options" style="display:none;">
                                        <div class="chat-config-row" style="margin-bottom:6px;">
                                            <div class="chat-field-label">プロバイダ:</div>
                                            <select id="chat-image-gen-provider" class="chat-field-input">
                                                <option value="openai">OpenAI (DALL-E)</option>
                                                <option value="stability">Stable Diffusion</option>
                                            </select>
                                        </div>
                                        <div id="chat-image-gen-dalle-options">
                                            <div class="chat-config-row" style="margin-bottom:6px;">
                                                <div class="chat-field-label">DALL-E モデル:</div>
                                                <select id="chat-image-gen-dalle-model" class="chat-field-input">
                                                    <option value="dall-e-3">DALL-E 3</option>
                                                    <option value="dall-e-2">DALL-E 2</option>
                                                </select>
                                            </div>
                                        </div>
                                        <div id="chat-image-gen-stability-options" style="display:none;">
                                            <div class="chat-config-row" style="margin-bottom:6px;">
                                                <div class="chat-field-label">SD WebUI URL:</div>
                                                <input type="text" id="chat-image-gen-stability-url" class="chat-field-input" placeholder="http://localhost:7860" />
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div id="chat-base-url-row">
                                    <div class="chat-field-label">Base URL <span style="color:var(--text-muted);font-size:0.7rem;">（任意）</span></div>
                                    <input type="text" id="chat-base-url" class="chat-field-input" placeholder="https://openrouter.ai/api/v1" />
                                </div>
                                <div>
                                    <div class="chat-field-label" style="display:flex;justify-content:space-between;">
                                        <span>Temperature</span>
                                        <span id="chat-temp-val" style="color:var(--accent-purple);">0.7</span>
                                    </div>
                                    <input type="range" id="chat-temperature" class="chat-field-input" min="0" max="2" step="0.05" value="0.7"
                                        oninput="document.getElementById('chat-temp-val').textContent=parseFloat(this.value).toFixed(2)"
                                        style="width:100%;accent-color:var(--accent-purple);" />
                                </div>
                                <div style="border-top:1px solid var(--glass-border);padding-top:8px;margin-top:4px;">
                                    <h4 style="font-size:0.82rem;font-weight:600;color:var(--text-secondary);margin:8px 0 4px;display:flex;align-items:center;gap:6px;"><i data-lucide="thermometer"></i> 動的温度調整</h4>
                                    <div class="chat-config-row" style="display:flex;align-items:center;gap:8px;margin:4px 0;">
                                        <label class="chat-config-label" style="display:flex;align-items:center;gap:6px;font-size:0.8rem;color:var(--text-secondary);cursor:pointer;">
                                            <input type="checkbox" id="chat-dynamic-temperature" class="chat-config-checkbox" style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" checked
                                                onchange="document.getElementById('chat-emotion-temperature-scale').disabled=!this.checked;" />
                                            <span>動的温度調整を有効にする</span>
                                        </label>
                                    </div>
                                    <div>
                                        <div class="chat-field-label" style="display:flex;justify-content:space-between;">
                                            <span>感情温度スケール</span>
                                            <span id="chat-emotion-temp-scale-val" style="color:var(--accent-purple);">0.20</span>
                                        </div>
                                        <input type="range" id="chat-emotion-temperature-scale" class="chat-field-input" min="0" max="1" step="0.05" value="0.2"
                                            oninput="document.getElementById('chat-emotion-temp-scale-val').textContent=parseFloat(this.value).toFixed(2)"
                                            style="width:100%;accent-color:var(--accent-purple);" />
                                    </div>
                                    <div>
                                        <div class="chat-field-label" style="display:flex;justify-content:space-between;">
                                            <span>Top P</span>
                                            <span id="chat-top-p-val" style="color:var(--accent-purple);">1.00</span>
                                        </div>
                                        <input type="range" id="chat-top-p" class="chat-field-input" min="0" max="1" step="0.05" value=""
                                            oninput="var v=parseFloat(this.value);document.getElementById('chat-top-p-val').textContent=isNaN(v)?'—':v.toFixed(2)"
                                            style="width:100%;accent-color:var(--accent-purple);" />
                                    </div>
                                </div>
                                <div>
                                    <div class="chat-field-label">Max Tokens</div>
                                    <input type="number" id="chat-max-tokens" class="chat-field-input" min="1" max="32768" value="2048" />
                                </div>
                            </div>
                        </details>
                        <!-- Context & System Prompt -->
                        <details data-category="context">
                            <summary><i data-lucide="message-circle"></i> コンテキスト <span class="chat-help-icon" onmouseenter="showHelpTooltip(event, 'context')" title="説明を表示" onmouseleave="hideHelpTooltip()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div>
                                    <div class="chat-field-label">表示履歴 (turns) <span style="color:var(--text-muted);font-size:0.7rem;">（ページロード時に遡る件数）</span></div>
                                    <input type="number" id="chat-display-history-turns" class="chat-field-input" min="1" max="200" value="20" />
                                </div>
                                <div>
                                    <div class="chat-field-label">最大ツール呼び出し回数</div>
                                    <input type="number" id="chat-max-tool-calls" class="chat-field-input" min="0" max="20" value="5" />
                                </div>
                                <div style="flex:1; display:flex; flex-direction:column; min-height:80px;">
                                    <div class="chat-field-label">システムプロンプト</div>
                                    <textarea id="chat-system-prompt" class="chat-field-input" rows="4"
                                        placeholder="（空白でデフォルト: ペルソナ名のアシスタント）"
                                        style="flex:1;resize:vertical;min-height:70px;max-height:300px;overflow-y:auto;"></textarea>
                                </div>
                                <!-- コンテキスト最適化 (v2.1) -->
                                <details class="chat-subsection" style="margin-top:10px;padding-top:8px;border-top:1px solid var(--glass-border);">
                                  <summary style="font-size:0.82rem;font-weight:600;color:var(--text-secondary);cursor:pointer;padding:4px 0;">🧠 コンテキスト最適化</summary>
                                  <div style="padding-top:8px;">

                                  <div class="chat-field-label">保存メッセージ数</div>
                                  <input type="number" id="chat-stored-msgs" class="chat-field-input" value="200" min="2" max="2000" />
                                  <div class="chat-field-hint" style="font-size:0.7rem;color:var(--text-muted);margin-top:-6px;margin-bottom:8px;">SQLiteに保存する最大メッセージ数（セッション永続化用）</div>

                                  <div class="chat-field-label">トークン上限</div>
                                  <input type="number" id="chat-context-max-tokens" class="chat-field-input" value="" placeholder="自動（モデル判定）" min="1000" max="1000000" />
                                  <div class="chat-field-hint" style="font-size:0.7rem;color:var(--text-muted);margin-top:-6px;margin-bottom:8px;">空欄でモデルのコンテキストウィンドウを自動判定</div>

                                  <div class="chat-field-label">圧縮閾値 <span id="threshold-display">80%</span></div>
                                  <input type="range" id="chat-compression-threshold" min="50" max="100" value="80" style="width:100%;margin:4px 0;" />

                                  <div class="chat-field-label">圧縮モード</div>
                                  <select id="chat-compression-mode" class="chat-field-input">
                                    <option value="auto">自動</option>
                                    <option value="light">軽度</option>
                                    <option value="normal">標準</option>
                                    <option value="aggressive">強力</option>
                                  </select>

                                  <div class="chat-field-label">完全保持ターン数</div>
                                  <input type="number" id="chat-keep-recent" class="chat-field-input" value="2" min="1" max="20" />

                                  <div class="chat-field-label">記憶プリロード数</div>
                                  <input type="number" id="chat-memory-preload" class="chat-field-input" value="3" min="0" max="20" />
                                  <div class="chat-field-hint" style="font-size:0.7rem;color:var(--text-muted);margin-top:-6px;margin-bottom:8px;">systemプロンプトに含める関連記憶の数。0で全件オンデマンド検索</div>

                                  <div style="display:flex;align-items:center;gap:8px;margin:6px 0;">
                                    <input type="checkbox" id="chat-compress-system" checked>
                                    <label for="chat-compress-system" style="font-size:0.8rem;">システムプロンプト圧縮</label>
                                  </div>
                                  <div style="display:flex;align-items:center;gap:8px;margin:6px 0;">
                                    <input type="checkbox" id="chat-compress-history" checked>
                                    <label for="chat-compress-history" style="font-size:0.8rem;">会話履歴圧縮</label>
                                  </div>
                                  <div style="display:flex;align-items:center;gap:8px;margin:6px 0;">
                                    <input type="checkbox" id="chat-parallel-tools" checked>
                                    <label for="chat-parallel-tools" style="font-size:0.8rem;">並列ツール実行</label>
                                  </div>
                                  <div style="display:flex;align-items:center;gap:8px;margin:6px 0;">
                                    <input type="checkbox" id="chat-llm-summary" checked>
                                    <label for="chat-llm-summary" style="font-size:0.8rem;">LLM要約圧縮</label>
                                  </div>
                                  <div style="display:flex;align-items:center;gap:8px;margin:6px 0;">
                                    <input type="checkbox" id="chat-episode-consolidation" checked>
                                    <label for="chat-episode-consolidation" style="font-size:0.8rem;">エピソード統合</label>
                                  </div>
                                  <div style="display:flex;align-items:center;gap:8px;margin:6px 0;">
                                    <input type="checkbox" id="chat-episode-search" checked>
                                    <label for="chat-episode-search" style="font-size:0.8rem;">エピソード検索</label>
                                  </div>
                                  </div>
                                </details>
                            </div>
                        </details>
                        <!-- Memory extraction -->
                        <details data-category="memory">
                            <summary><i data-lucide="brain"></i> 記憶・抽出 <span class="chat-help-icon" onmouseenter="showHelpTooltip(event, 'memory')" title="説明を表示" onmouseleave="hideHelpTooltip()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-auto-extract" checked
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-auto-extract" class="chat-field-label" style="margin:0;cursor:pointer;">ターン毎に記憶を自動抽出 (Mem0方式)</label>
                                </div>
                                <div>
                                    <div class="chat-field-label">抽出モデル <span style="color:var(--text-muted);font-size:0.7rem;">（空白でチャットと同モデル）</span></div>
                                    <input type="text" id="chat-extract-model" class="chat-field-input"
                                        placeholder="例: claude-haiku-4-5, gpt-4o-mini" />
                                </div>
                                <div>
                                    <div class="chat-field-label">抽出 Max Tokens</div>
                                    <input type="number" id="chat-extract-max-tokens" class="chat-field-input" min="64" max="2048" value="512" />
                                </div>
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-enable-memory-tools" checked
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-enable-memory-tools" class="chat-field-label" style="margin:0;cursor:pointer;">LLMに組み込みメモリツールを渡す</label>
                                </div>
                            </div>
                        </details>
                        <!-- MCP Servers -->
                        <details data-category="tools">
                            <summary><i data-lucide="battery-charging"></i> MCPサーバー <span class="chat-help-icon" onmouseenter="showHelpTooltip(event, 'tools')" title="説明を表示" onmouseleave="hideHelpTooltip()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body" id="chat-mcp-section">
                                <div id="chat-mcp-server-list" style="display:flex;flex-direction:column;gap:2px;margin-bottom:8px;"></div>
                                <div>
                                    <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:4px;">Claude の mcp.json 形式で貼り付け・編集できます</div>
                                    <textarea id="chat-mcp-json" class="chat-field-input" rows="6"
                                        style="resize:vertical;min-height:100px;font-family:monospace;font-size:0.73rem;line-height:1.45;"
                                        placeholder='[{{&#10;  "name": "memory-mcp",&#10;  "command": "{sys.executable}",&#10;  "args": ["-m", "nous.main"],&#10;  "env": {{}}&#10;}}]'></textarea>
                                    <div id="chat-mcp-json-error" style="font-size:0.72rem;color:var(--accent-red);margin-top:3px;display:none;"></div>
                                </div>
                                <div>
                                    <div class="chat-field-label" style="display:flex;justify-content:space-between;">
                                        <span>ツール結果最大文字数</span>
                                        <span id="chat-tool-max-val" style="color:var(--accent-purple);">4000</span>
                                    </div>
                                    <input type="range" id="chat-tool-result-max" class="chat-field-input" min="500" max="20000" step="500" value="4000"
                                        oninput="document.getElementById('chat-tool-max-val').textContent=this.value"
                                        style="width:100%;accent-color:var(--accent-purple);" />
                                </div>
                            </div>
                        </details>
                        <!-- Skills -->
                        <details data-category="skills">
                            <summary><i data-lucide="target"></i> Skills <span class="chat-help-icon" onmouseenter="showHelpTooltip(event, 'skills')" title="説明を表示" onmouseleave="hideHelpTooltip()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body" id="chat-skills-section">
                                <div id="chat-skills-list" style="display:flex;flex-direction:column;gap:4px;"></div>
                            </div>
                        </details>
                        <!-- Reflection -->
                        <details data-category="reflection">
                            <summary><i data-lucide="crystal-ball"></i> リフレクション <span class="chat-help-icon" onmouseenter="showHelpTooltip(event, 'reflection')" title="説明を表示" onmouseleave="hideHelpTooltip()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-reflection-enabled" checked
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-reflection-enabled" class="chat-field-label" style="margin:0;cursor:pointer;">リフレクション有効</label>
                                </div>
                                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                                    <div>
                                        <div class="chat-field-label">閾値</div>
                                        <input type="number" id="chat-reflection-threshold" class="chat-field-input"
                                            min="0.1" max="100" step="0.1" value="1.0" />
                                    </div>
                                    <div>
                                        <div class="chat-field-label">最小間隔 (時間)</div>
                                        <input type="number" id="chat-reflection-interval" class="chat-field-input"
                                            min="0" max="168" step="0.5" value="1.0" />
                                    </div>
                                </div>
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-session-summarize" checked
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-session-summarize" class="chat-field-label" style="margin:0;cursor:pointer;">セッション要約</label>
                                </div>
                            </div>
                        </details>
                        <!-- Mental Model -->
                        <details data-category="mental">
                            <summary><i data-lucide="puzzle"></i> メンタルモデル <span class="chat-help-icon" onmouseenter="showHelpTooltip(event, 'mental')" title="説明を表示" onmouseleave="hideHelpTooltip()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-mental-model-enabled" checked
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-mental-model-enabled" class="chat-field-label" style="margin:0;cursor:pointer;">メンタルモデル抽出を有効</label>
                                </div>
                                <div>
                                    <div class="chat-field-label">最小サンプル数</div>
                                    <input type="number" id="chat-mental-model-min-samples" class="chat-field-input"
                                        min="1" max="20" value="3" />
                                </div>
                            </div>
                        </details>
                        <!-- Retrieval weights -->
                        <details data-category="weights">
                            <summary><i data-lucide="scale"></i> 検索重み <span class="chat-help-icon" onmouseenter="showHelpTooltip(event, 'weights')" title="説明を表示" onmouseleave="hideHelpTooltip()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div>
                                    <div class="chat-field-label" style="display:flex;justify-content:space-between;">
                                        <span>鮮度</span>
                                        <span id="chat-recency-weight-val" style="color:var(--accent-purple);">0.30</span>
                                    </div>
                                    <input type="range" id="chat-recency-weight" class="chat-field-input" min="0" max="1" step="0.05" value="0.3"
                                        oninput="document.getElementById('chat-recency-weight-val').textContent=parseFloat(this.value).toFixed(2)"
                                        style="width:100%;accent-color:var(--accent-purple);" />
                                </div>
                                <div>
                                    <div class="chat-field-label" style="display:flex;justify-content:space-between;">
                                        <span>重要度</span>
                                        <span id="chat-importance-weight-val" style="color:var(--accent-purple);">0.30</span>
                                    </div>
                                    <input type="range" id="chat-importance-weight" class="chat-field-input" min="0" max="1" step="0.05" value="0.3"
                                        oninput="document.getElementById('chat-importance-weight-val').textContent=parseFloat(this.value).toFixed(2)"
                                        style="width:100%;accent-color:var(--accent-purple);" />
                                </div>
                                <div>
                                    <div class="chat-field-label" style="display:flex;justify-content:space-between;">
                                        <span>関連性</span>
                                        <span id="chat-relevance-weight-val" style="color:var(--accent-purple);">0.40</span>
                                    </div>
                                    <input type="range" id="chat-relevance-weight" class="chat-field-input" min="0" max="1" step="0.05" value="0.4"
                                        oninput="document.getElementById('chat-relevance-weight-val').textContent=parseFloat(this.value).toFixed(2)"
                                        style="width:100%;accent-color:var(--accent-purple);" />
                                </div>
                            </div>
                        </details>
                        <!-- Housekeeping & Other -->
                        <details data-category="other">
                            <summary><i data-lucide="broom"></i> 整理・その他 <span class="chat-help-icon" onmouseenter="showHelpTooltip(event, 'other')" title="説明を表示" onmouseleave="hideHelpTooltip()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div>
                                    <div class="chat-field-label">自動整理 閾値 (goals 合計のみ)</div>
                                    <input type="number" id="chat-housekeeping-threshold" class="chat-field-input" min="1" max="100" value="10" />
                                </div>
                                <button class="chat-clear-btn" style="margin-top:4px;" onclick="runHousekeeping()"><i data-lucide="broom"></i> 今すぐ整理</button>
                                <div id="chat-housekeeping-status" style="font-size:0.75rem; text-align:center; min-height:16px;"></div>
                                <div style="border-top:1px solid var(--glass-border);padding-top:8px;display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-sandbox-enabled"
                                        style="width:15px;height:15px;accent-color:var(--accent-blue);cursor:pointer;"
                                        onchange="onSandboxEnabledChange()" />
                                    <label for="chat-sandbox-enabled" class="chat-field-label" style="margin:0;cursor:pointer;">コード実行 (Dockerサンドボックス)</label>
                                </div>
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-debug-mode"
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-debug-mode" class="chat-field-label" style="margin:0;cursor:pointer;"><i data-lucide="bug"></i> デバッグモード</label>
                                </div>
                            </div>
                        </details>
                    </div>
                    <!-- Sticky footer buttons -->
                    <div class="settings-footer">
                        <button class="chat-save-btn" onclick="saveChatConfig()" aria-label="チャット設定を保存"><i data-lucide="save"></i> 設定を保存</button>
                        <button class="chat-clear-btn" onclick="clearChatHistory()" aria-label="会話履歴をリセット"><i data-lucide="trash-2"></i> 会話をリセット</button>
                        <div id="chat-config-status" style="font-size:0.75rem; text-align:center; min-height:16px;"></div>
                    </div>
                </div>
            </div>
            <!-- highlight.js for syntax highlighting in chat bubbles -->
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
            <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js" crossorigin="anonymous"></script>
            <!-- Media viewer overlay -->
            <div id="media-viewer-overlay" onclick="closeMediaViewer()">
                <div id="media-viewer-inner" onclick="event.stopPropagation()"></div>
            </div>
            <!-- Memory edit modal -->
            <div id="mem-edit-overlay" onclick="closeMemEdit()">
                <div id="mem-edit-modal" onclick="event.stopPropagation()">
                    <div style="font-size:0.85rem;font-weight:600;color:var(--text-primary);">メモリ編集</div>
                    <div>
                        <div class="mem-edit-label">内容</div>
                        <textarea id="mem-edit-content"></textarea>
                    </div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                        <div>
                            <div class="mem-edit-label">重要度 (0.0-1.0)</div>
                            <input type="number" id="mem-edit-importance" min="0" max="1" step="0.05" value="0.5" />
                        </div>
                        <div>
                            <div class="mem-edit-label">タグ (カンマ区切り)</div>
                            <input type="text" id="mem-edit-tags" placeholder="goal, active" />
                        </div>
                    </div>
                    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:4px;">
                        <button class="chat-clear-btn" style="width:auto;padding:6px 14px;" onclick="deleteMemCard()" aria-label="メモリを削除">削除</button>
                        <button class="chat-save-btn" style="width:auto;padding:6px 14px;" onclick="saveMemEdit()" aria-label="メモリを保存">保存</button>
                    </div>
                </div>
            </div>
        </section>""" + render_coding_agent_panel()


def render_chat_js() -> str:
    """Return the JavaScript for the chat tab.

    The actual JS is loaded via <script src="/static/chat.js"> in render_head().
    This function exists for dashboard.py's tab_js assembly compatibility.
    """
    return ""
