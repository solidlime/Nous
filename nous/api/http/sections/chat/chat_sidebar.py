"""Chat settings sidebar — provider, MCP, TTS, image gen, context, and other settings."""

import sys


def render_chat_sidebar() -> str:
    """Return the settings sidebar HTML with all configuration panels."""
    return f"""
                <!-- Settings sidebar -->
                <div id="settings-panel" class="glass" style="margin:0; border-radius:0; border-left:1px solid var(--glass-border); padding:0;">
                    <!-- Mobile close button -->
                    <button id="settings-panel-close-btn" class="settings-panel-close" onclick="N.Chat.core.toggleSettings()" title="設定パネルを閉じる" aria-label="設定パネルを閉じる"><i data-lucide="x"></i></button>
                    <div class="settings-scroll-container">
                        <div style="position:sticky;top:0;z-index:10;background:var(--glass-bg);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);font-size:0.9rem;font-weight:600;color:var(--text-primary);padding:12px 0 8px;margin:0 -16px 8px;border-bottom:1px solid var(--glass-border);display:flex;align-items:center;gap:8px;">
                            <span style="font-size:1.1rem;margin-left:16px;"><i data-lucide="settings"></i></span>
                            <span>チャット設定</span>
                        </div>
                        <!-- Provider / Model / API -->
                        <details data-category="core" open>
                            <summary><i data-lucide="wrench"></i> 基本設定 <span class="chat-help-icon" onmouseenter="N.Chat.core.showHelp(event, 'core')" title="説明を表示" onmouseleave="N.Chat.core.hideHelp()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div>
                                    <div class="chat-field-label">プロバイダー</div>
                                    <select id="chat-provider" class="chat-field-input" onchange="N.Chat.settings.onProviderChange()">
                                        <option value="anthropic">Anthropic (Claude)</option>
                                        <option value="openai">OpenAI</option>
                                        <option value="openrouter">OpenRouter</option>
                                        <option value="google">Google (Gemini)</option>
                                        <option value="opencode_go">OpenCode Go (DeepSeek V4)</option>
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
                                    <input type="number" id="chat-max-tokens" class="chat-field-input" min="1" max="131072" value="8192" />
                                </div>
                            </div>
                        </details>
                        <!-- Context & System Prompt -->
                        <details data-category="context">
                            <summary><i data-lucide="message-circle"></i> コンテキスト <span class="chat-help-icon" onmouseenter="N.Chat.core.showHelp(event, 'context')" title="説明を表示" onmouseleave="N.Chat.core.hideHelp()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div>
                                    <div class="chat-field-label">表示履歴 (turns) <span style="color:var(--text-muted);font-size:0.7rem;">（ページロード時に遡る件数）</span></div>
                                    <input type="number" id="chat-display-history-turns" class="chat-field-input" min="1" max="5000" value="10" />
                                    <span class="setting-hint">表示される履歴数です。AIが完全に記憶するターン数は「完全保持ターン数」で設定します。</span>
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
                                  <input type="number" id="chat-keep-recent" class="chat-field-input" value="2" min="1" />
                                  <span class="setting-hint">AIが要約せず完全に保持する最新の会話ターン数です。表示履歴数より小さく設定することを推奨します。</span>

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
                                    <input type="checkbox" id="chat-episode-search" checked>
                                    <label for="chat-episode-search" style="font-size:0.8rem;">エピソード検索</label>
                                  </div>
                                  </div>
                                </details>
                            </div>
                        </details>
                        <!-- Memory extraction -->
                        <details data-category="memory">
                            <summary><i data-lucide="brain"></i> 記憶・抽出 <span class="chat-help-icon" onmouseenter="N.Chat.core.showHelp(event, 'memory')" title="説明を表示" onmouseleave="N.Chat.core.hideHelp()"><i data-lucide="help-circle"></i></span></summary>
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
                            <summary><i data-lucide="battery-charging"></i> MCPサーバー <span class="chat-help-icon" onmouseenter="N.Chat.core.showHelp(event, 'tools')" title="説明を表示" onmouseleave="N.Chat.core.hideHelp()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body" id="chat-mcp-section">
                                <div id="chat-mcp-server-list" style="display:flex;flex-direction:column;gap:2px;margin-bottom:8px;"></div>
                                <div>
                                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                                        <div style="font-size:0.72rem;color:var(--text-muted);">Claude の mcp.json 形式で貼り付け・編集できます</div>
                                        <button type="button" id="chat-mcp-format-btn" class="mem-action-btn" style="font-size:0.65rem;padding:2px 8px;" onclick="N.Chat.settings.formatMcpJson()" title="JSONを整形">整形</button>
                                    </div>
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
                                    <input type="range" id="chat-tool-result-max" class="chat-field-input" min="500" max="100000" step="500" value="4000"
                                        oninput="document.getElementById('chat-tool-max-val').textContent=this.value"
                                        style="width:100%;accent-color:var(--accent-purple);" />
                                </div>
                            </div>
                        </details>
                        <!-- Skills -->
                        <details data-category="skills">
                            <summary><i data-lucide="target"></i> Skills <span class="chat-help-icon" onmouseenter="N.Chat.core.showHelp(event, 'skills')" title="説明を表示" onmouseleave="N.Chat.core.hideHelp()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body" id="chat-skills-section">
                                <div id="chat-skills-list" style="display:flex;flex-direction:column;gap:4px;"></div>
                            </div>
                        </details>
                        <!-- Reflection -->
                        <details data-category="reflection">
                            <summary><i data-lucide="sparkles"></i> リフレクション <span class="chat-help-icon" onmouseenter="N.Chat.core.showHelp(event, 'reflection')" title="説明を表示" onmouseleave="N.Chat.core.hideHelp()"><i data-lucide="help-circle"></i></span></summary>
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
                            <summary><i data-lucide="puzzle"></i> メンタルモデル <span class="chat-help-icon" onmouseenter="N.Chat.core.showHelp(event, 'mental')" title="説明を表示" onmouseleave="N.Chat.core.hideHelp()"><i data-lucide="help-circle"></i></span></summary>
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
                            <summary><i data-lucide="scale"></i> 検索重み <span class="chat-help-icon" onmouseenter="N.Chat.core.showHelp(event, 'weights')" title="説明を表示" onmouseleave="N.Chat.core.hideHelp()"><i data-lucide="help-circle"></i></span></summary>
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
                                <div>
                                    <div class="chat-field-label" style="display:flex;justify-content:space-between;">
                                        <span>RRF K値</span>
                                        <span id="chat-retrieval-rrf-k-val" style="color:var(--accent-purple);">5</span>
                                    </div>
                                    <input type="range" id="chat-retrieval-rrf-k" class="chat-field-input" min="1" max="100" step="1" value="5"
                                        oninput="document.getElementById('chat-retrieval-rrf-k-val').textContent=this.value"
                                        style="width:100%;accent-color:var(--accent-purple);" />
                                </div>
                            </div>
                        </details>
                        <!-- 画像生成 -->
                        <details data-category="image" id="chat-image-section">
                            <summary><i data-lucide="image"></i> 画像生成 <span class="chat-help-icon" onmouseenter="N.Chat.core.showHelp(event, 'image')" title="説明を表示" onmouseleave="N.Chat.core.hideHelp()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
                                    <span class="chat-field-label" style="margin:0;">画像生成を有効化</span>
                                    <label class="toggle-switch">
                                        <input type="checkbox" id="chat-image-gen-enabled" />
                                        <span class="toggle-slider"></span>
                                    </label>
                                </div>
                                <div id="chat-image-options">
                                    <div id="chat-image-status" class="voice-status voice-status-checking" role="status" aria-live="polite">
                                        <span class="voice-status-dot"></span>
                                        <span class="voice-status-text">接続確認中...</span>
                                    </div>
                                    <div>
                                        <div class="chat-field-label">ComfyUI URL</div>
                                        <div style="display:flex;gap:4px;">
                                            <input type="text" id="chat-image-gen-comfyui-url" class="chat-field-input" placeholder="http://192.168.50.150:8188" style="flex:1;" />
                                        </div>
                                    </div>
                                    <div>
                                        <div class="chat-field-label">チェックポイント</div>
                                        <input type="text" id="chat-image-gen-checkpoint" class="chat-field-input" placeholder="noobaiXLNAIXL_epsilonPred11Version.safetensors" />
                                    </div>
                                    <!-- 自画像生成プロンプト -->
                                    <div>
                                        <div class="chat-field-label" style="font-size:0.78rem;">自画像プロンプト <span style="color:var(--text-muted);font-size:0.7rem;">（キャラの外見タグ・LoRAトリガーワード等）</span></div>
                                        <textarea id="chat-image-gen-self-portrait-prompt" class="chat-field-input" placeholder="1girl, solo, purple eyes, short white hair, witch hat, holding ornate key-shaped staff, &lt;lora:herta_v1:0.8&gt;" rows="3" style="width:100%;resize:vertical;font-size:0.78rem;"></textarea>
                                    </div>
                                    <div>
                                        <div class="chat-field-label" style="font-size:0.78rem;">ネガティブプロンプト <span style="font-weight:300;color:var(--text-dim);">(低画質・崩れ除外タグ)</span></div>
                                        <textarea id="chat-image-gen-negative-prompt" class="chat-field-input" style="min-height:48px;width:100%;" placeholder="lowres, bad anatomy, bad hands, text, error"></textarea>
                                    </div>
                                    <div>
                                        <div style="display:flex;justify-content:space-between;align-items:center;">
                                            <span class="chat-field-label" style="font-size:0.78rem;">LoRA</span>
                                            <button type="button" id="chat-image-gen-lora-add" class="chat-btn-sm" style="font-size:0.72rem;">+ 追加</button>
                                        </div>
                                        <div id="chat-image-gen-lora-list" style="display:flex;flex-direction:column;gap:4px;margin-top:4px;"></div>
                                    </div>
                                    <div>
                                        <div class="chat-field-label">解像度</div>
                                        <div style="display:flex;gap:8px;align-items:center;">
                                            <span style="font-size:0.78rem;">W</span>
                                            <input type="number" id="chat-image-gen-width" class="chat-field-input" value="1024" min="256" max="2048" step="64" style="width:90px;" />
                                            <span style="font-size:0.78rem;">H</span>
                                            <input type="number" id="chat-image-gen-height" class="chat-field-input" value="1024" min="256" max="2048" step="64" style="width:90px;" />
                                        </div>
                                    </div>
                                    <div>
                                        <div class="chat-field-label" style="font-size:0.78rem;">最大解像度（LLMが指定できる上限）</div>
                                        <div style="display:flex;gap:8px;align-items:center;">
                                            <span style="font-size:0.78rem;">W</span>
                                            <input type="number" id="chat-image-gen-max-width" class="chat-field-input" value="1200" min="64" max="4096" step="64" style="width:90px;" />
                                            <span style="font-size:0.78rem;">H</span>
                                            <input type="number" id="chat-image-gen-max-height" class="chat-field-input" value="1200" min="64" max="4096" step="64" style="width:90px;" />
                                        </div>
                                    </div>
                                    <div>
                                        <div style="display:flex;justify-content:space-between;">
                                            <span class="chat-field-label" style="font-size:0.78rem;">Steps</span>
                                            <span id="chat-image-gen-steps-val" style="font-size:0.72rem;color:var(--accent-purple);">28</span>
                                        </div>
                                        <input type="range" id="chat-image-gen-steps" class="chat-field-input" min="1" max="100" step="1" value="28" oninput="document.getElementById('chat-image-gen-steps-val').textContent=this.value" style="width:100%;accent-color:var(--accent-purple);" />
                                    </div>
                                    <div>
                                        <div style="display:flex;justify-content:space-between;">
                                            <span class="chat-field-label" style="font-size:0.78rem;">CFG Scale</span>
                                            <span id="chat-image-gen-cfg-val" style="font-size:0.72rem;color:var(--accent-purple);">5.5</span>
                                        </div>
                                        <input type="range" id="chat-image-gen-cfg" class="chat-field-input" min="1.0" max="30.0" step="0.5" value="5.5" oninput="document.getElementById('chat-image-gen-cfg-val').textContent=parseFloat(this.value).toFixed(1)" style="width:100%;accent-color:var(--accent-purple);" />
                                    </div>
                                    <details style="margin-top:12px;">
                                        <summary style="font-size:0.82rem;color:var(--text-muted);cursor:pointer;">詳細設定</summary>
                                        <div style="display:flex;flex-direction:column;gap:10px;margin-top:8px;padding-left:4px;">
                                            <div>
                                                <div class="chat-field-label" style="font-size:0.78rem;">Sampler</div>
                                                <select id="chat-image-gen-sampler" class="chat-field-input" style="width:100%;">
                                                    <option value="euler">Euler</option>
                                                    <option value="euler_ancestral" selected>Euler Ancestral</option>
                                                    <option value="dpmpp_2m">DPM++ 2M</option>
                                                    <option value="dpmpp_2m_sde">DPM++ 2M SDE</option>
                                                    <option value="dpmpp_3m_sde">DPM++ 3M SDE</option>
                                                    <option value="dpm_2">DPM 2</option>
                                                    <option value="dpm_2_ancestral">DPM 2 Ancestral</option>
                                                    <option value="lcm">LCM</option>
                                                </select>
                                            </div>
                                            <div>
                                                <div class="chat-field-label" style="font-size:0.78rem;">Scheduler</div>
                                                <select id="chat-image-gen-scheduler" class="chat-field-input" style="width:100%;">
                                                    <option value="normal" selected>Normal</option>
                                                    <option value="karras">Karras</option>
                                                    <option value="exponential">Exponential</option>
                                                    <option value="sgm_uniform">SGM Uniform</option>
                                                    <option value="simple">Simple</option>
                                                    <option value="ddim_uniform">DDIM Uniform</option>
                                                </select>
                                            </div>
                                            <div>
                                                <div style="display:flex;justify-content:space-between;">
                                                    <span class="chat-field-label" style="font-size:0.78rem;">Denoise (img2img)</span>
                                                    <span id="chat-image-gen-denoise-val" style="font-size:0.72rem;color:var(--accent-purple);">0.70</span>
                                                </div>
                                                <input type="range" id="chat-image-gen-denoise" class="chat-field-input" min="0.1" max="1.0" step="0.05" value="0.7" oninput="document.getElementById('chat-image-gen-denoise-val').textContent=parseFloat(this.value).toFixed(2)" style="width:100%;accent-color:var(--accent-purple);" />
                                            </div>
                                            <div>
                                                <div class="chat-field-label" style="font-size:0.78rem;">乱数シード（0=ランダム）</div>
                                                <input type="number" id="chat-image-gen-seed" class="chat-field-input" value="0" min="0" style="width:100%;" />
                                            </div>
                                            <div style="display:none;">
                                                <select id="chat-image-gen-speed-lora-method"><option value="">使用しない</option><option value="lcm">LCM</option><option value="lightning">Lightning</option><option value="hyper">Hyper-SD</option><option value="tcd">TCD</option></select>
                                                <input type="text" id="chat-image-gen-speed-lora-path" />
                                                <input type="number" id="chat-image-gen-speed-lora-weight" value="1.0" />
                                            </div>
                                        </div>
                                    </details>
                                    <div style="display:flex;gap:8px;align-items:center;">
                                        <button class="chat-clear-btn" style="font-size:0.78rem;padding:6px 12px;" onclick="N.Chat.settings.testImageGen()"><i data-lucide="play"></i> テスト生成</button>
                                        <span id="chat-image-test-status" style="font-size:0.72rem;color:var(--text-muted);min-height:16px;"></span>
                                    </div>
                                </div>
                            </div>
                        </details>
                        <!-- Voice / TTS (TE04) -->
                        <details data-category="voice" id="chat-voice-section">
                            <summary><i data-lucide="volume-2"></i> 音声 <span class="chat-help-icon" onmouseenter="N.Chat.core.showHelp(event, 'voice')" title="説明を表示" onmouseleave="N.Chat.core.hideHelp()"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
                                    <span class="chat-field-label" style="margin:0;">音声合成を有効化</span>
                                    <label class="toggle-switch">
                                        <input type="checkbox" id="chat-voice-enabled" />
                                        <span class="toggle-slider"></span>
                                    </label>
                                </div>
                                <div id="chat-voice-options">
                                    <!-- Connection status -->
                                    <div id="chat-voice-status" class="voice-status voice-status-checking" role="status" aria-live="polite">
                                        <span class="voice-status-dot"></span>
                                        <span class="voice-status-text">接続確認中...</span>
                                    </div>
                                    <!-- Server URL -->
                                    <div>
                                        <div class="chat-field-label">Irodori サーバーURL</div>
                                        <input type="url" id="chat-voice-url" class="chat-field-input"
                                            placeholder="http://192.168.50.150:8088/v1"
                                            aria-label="TTSサーバーのURL" />
                                    </div>
                                    <!-- Voice model name -->
                                    <div>
                                        <div class="chat-field-label">音声 (Voice)</div>
                                        <input type="text" id="chat-voice-model" class="chat-field-input"
                                            placeholder="sample"
                                            aria-label="音声名" />
                                    </div>
                                    <!-- Checkboxes -->
                                    <div style="display:flex;align-items:center;gap:8px;">
                                        <input type="checkbox" id="chat-voice-emotion-link" checked
                                            style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                        <label for="chat-voice-emotion-link" class="chat-field-label" style="margin:0;cursor:pointer;">感情を音声に反映</label>
                                    </div>
                                    <div style="display:flex;align-items:center;gap:8px;">
                                        <input type="checkbox" id="chat-voice-auto-play"
                                            style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                        <label for="chat-voice-auto-play" class="chat-field-label" style="margin:0;cursor:pointer;">応答を自動再生</label>
                                    </div>
                                    <!-- Voice volume -->
                                    <div>
                                        <div style="display:flex;justify-content:space-between;">
                                            <span class="chat-field-label" style="font-size:0.78rem;">音量</span>
                                            <span id="chat-voice-volume-val" style="font-size:0.72rem;color:var(--accent-purple);">100%</span>
                                        </div>
                                        <input type="range" id="chat-voice-volume" class="chat-field-input"
                                            min="0.0" max="1.0" step="0.05" value="1.0"
                                            oninput="document.getElementById('chat-voice-volume-val').textContent=Math.round(this.value*100)+'%'"
                                            style="width:100%;accent-color:var(--accent-purple);" />
                                    </div>
                                    <!-- Voice speed -->
                                    <div>
                                        <div style="display:flex;justify-content:space-between;">
                                            <span class="chat-field-label" style="font-size:0.78rem;">話速</span>
                                            <span id="chat-voice-speed-val" style="font-size:0.72rem;color:var(--accent-purple);">1.0x</span>
                                        </div>
                                        <input type="range" id="chat-voice-speed" class="chat-field-input"
                                            min="0.25" max="4.0" step="0.25" value="1.0"
                                            oninput="document.getElementById('chat-voice-speed-val').textContent=parseFloat(this.value).toFixed(2)+'x'"
                                            style="width:100%;accent-color:var(--accent-purple);" />
                                    </div>
                                    <!-- Irodori advanced params -->
                                    <details style="margin-top:12px;">
                                        <summary style="font-size:0.82rem;color:var(--text-muted);cursor:pointer;">詳細設定</summary>
                                        <div style="display:flex;flex-direction:column;gap:10px;margin-top:8px;padding-left:4px;">
                                            <!-- num_steps: range 10-50, step 1, default 30 -->
                                            <div>
                                                <div style="display:flex;justify-content:space-between;">
                                                    <span class="chat-field-label" style="font-size:0.78rem;">推論ステップ数</span>
                                                    <span id="chat-irodori-num-steps-val" style="font-size:0.72rem;color:var(--accent-purple);">30</span>
                                                </div>
                                                <input type="range" id="chat-irodori-num-steps" class="chat-field-input"
                                                    min="10" max="50" step="1" value="30"
                                                    oninput="document.getElementById('chat-irodori-num-steps-val').textContent=this.value"
                                                    style="width:100%;accent-color:var(--accent-purple);" />
                                            </div>
                                            <!-- cfg_scale_text: range 1.0-5.0, step 0.1, default 3.2 -->
                                            <div>
                                                <div style="display:flex;justify-content:space-between;">
                                                    <span class="chat-field-label" style="font-size:0.78rem;">テキスト忠実度</span>
                                                    <span id="chat-irodori-cfg-text-val" style="font-size:0.72rem;color:var(--accent-purple);">3.2</span>
                                                </div>
                                                <input type="range" id="chat-irodori-cfg-scale-text" class="chat-field-input"
                                                    min="1.0" max="5.0" step="0.1" value="3.2"
                                                    oninput="document.getElementById('chat-irodori-cfg-text-val').textContent=parseFloat(this.value).toFixed(1)"
                                                    style="width:100%;accent-color:var(--accent-purple);" />
                                            </div>
                                            <!-- cfg_scale_speaker: range 1.0-8.0, step 0.1, default 5.0 -->
                                            <div>
                                                <div style="display:flex;justify-content:space-between;">
                                                    <span class="chat-field-label" style="font-size:0.78rem;">話者再現度</span>
                                                    <span id="chat-irodori-cfg-speaker-val" style="font-size:0.72rem;color:var(--accent-purple);">5.0</span>
                                                </div>
                                                <input type="range" id="chat-irodori-cfg-scale-speaker" class="chat-field-input"
                                                    min="1.0" max="8.0" step="0.1" value="5.0"
                                                    oninput="document.getElementById('chat-irodori-cfg-speaker-val').textContent=parseFloat(this.value).toFixed(1)"
                                                    style="width:100%;accent-color:var(--accent-purple);" />
                                            </div>
                                            <!-- cfg_scale_caption: range 1.0-8.0, step 0.1, default 4.2 -->
                                            <div>
                                                <div style="display:flex;justify-content:space-between;">
                                                    <span class="chat-field-label" style="font-size:0.78rem;">感情・スタイル強度</span>
                                                    <span id="chat-irodori-cfg-caption-val" style="font-size:0.72rem;color:var(--accent-purple);">4.2</span>
                                                </div>
                                                <input type="range" id="chat-irodori-cfg-scale-caption" class="chat-field-input"
                                                    min="1.0" max="8.0" step="0.1" value="4.2"
                                                    oninput="document.getElementById('chat-irodori-cfg-caption-val').textContent=parseFloat(this.value).toFixed(1)"
                                                    style="width:100%;accent-color:var(--accent-purple);" />
                                            </div>
                                            <!-- chunk_min_chars: range 30-200, step 5, default 85 -->
                                            <div>
                                                <div style="display:flex;justify-content:space-between;">
                                                    <span class="chat-field-label" style="font-size:0.78rem;">最小チャンク文字数</span>
                                                    <span id="chat-irodori-chunk-min-val" style="font-size:0.72rem;color:var(--accent-purple);">85</span>
                                                </div>
                                                <input type="range" id="chat-irodori-chunk-min-chars" class="chat-field-input"
                                                    min="30" max="200" step="5" value="85"
                                                    oninput="document.getElementById('chat-irodori-chunk-min-val').textContent=this.value"
                                                    style="width:100%;accent-color:var(--accent-purple);" />
                                            </div>
                                            <!-- seed: number input, 0=random -->
                                            <div>
                                                <div class="chat-field-label" style="font-size:0.78rem;">乱数シード（0=ランダム）</div>
                                                <input type="number" id="chat-irodori-seed" class="chat-field-input"
                                                    value="0" min="0"
                                                    style="width:100%;" />
                                            </div>
                                        </div>
                                    </details>
                                    <!-- Test playback -->
                                    <div style="display:flex;gap:8px;align-items:center;margin-top:4px;">
                                        <button class="chat-clear-btn" style="font-size:0.78rem;padding:6px 12px;" onclick="testVoicePlayback()" aria-label="音声をテスト再生"><i data-lucide="play"></i> テスト再生</button>
                                        <span id="chat-voice-test-status" style="font-size:0.72rem;color:var(--text-muted);min-height:16px;"></span>
                                    </div>
                                </div>
                            </div>
                        </details>
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
                        </details>
                        <!-- Auto-capture (moved from Settings) -->
                        <details data-category="auto_capture">
                            <summary><i data-lucide="camera"></i> 自動キャプチャ</summary>
                            <div class="details-body">
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-auto-capture-enabled"
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-auto-capture-enabled" class="chat-field-label" style="margin:0;cursor:pointer;">自動キャプチャ有効</label>
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
                        </details>
                        <!-- Memory enrichment (moved from Settings) -->
                        <details data-category="memory_enrichment">
                            <summary><i data-lucide="layers"></i> 記憶エンリッチメント</summary>
                            <div class="details-body">
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-memory-enrichment-enabled"
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-memory-enrichment-enabled" class="chat-field-label" style="margin:0;cursor:pointer;">記憶エンリッチメント有効</label>
                                </div>
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-memory-enrichment-auto-run"
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-memory-enrichment-auto-run" class="chat-field-label" style="margin:0;cursor:pointer;">自動実行</label>
                                </div>
                                <div>
                                    <div class="chat-field-label">実行間隔（分）</div>
                                    <input type="number" id="chat-memory-enrichment-interval" class="chat-field-input" min="1" step="1" value="60" />
                                </div>
                                <div>
                                    <div class="chat-field-label">プロバイダ</div>
                                    <input type="text" id="chat-memory-enrichment-provider" class="chat-field-input" placeholder="例: openrouter" />
                                </div>
                                <div>
                                    <div class="chat-field-label">モデル</div>
                                    <input type="text" id="chat-memory-enrichment-model" class="chat-field-input" placeholder="例: openai/gpt-4o-mini" />
                                </div>
                                <div>
                                    <div class="chat-field-label">Base URL</div>
                                    <input type="text" id="chat-memory-enrichment-base-url" class="chat-field-input" placeholder="https://openrouter.ai/api/v1" />
                                </div>
                                <div>
                                    <div class="chat-field-label">最小文字数</div>
                                    <input type="number" id="chat-memory-enrichment-min-chars" class="chat-field-input" min="10" step="1" value="100" />
                                </div>
                                <div>
                                    <div class="chat-field-label">使用LLM</div>
                                    <input type="text" id="chat-memory-enrichment-llm" class="chat-field-input" placeholder="（空白でチャットと同モデル）" />
                                </div>
                                <div>
                                    <div class="chat-field-label">プロンプトテンプレート</div>
                                    <textarea id="chat-memory-enrichment-prompt-template" class="chat-field-input" rows="3" style="resize:vertical;font-size:0.78rem;"></textarea>
                                </div>
                                <div>
                                    <div class="chat-field-label">摘要粒度</div>
                                    <select id="chat-memory-enrichment-summary-granularity" class="chat-field-input">
                                        <option value="fine">細かめ</option>
                                        <option value="medium" selected>中程度</option>
                                        <option value="coarse">大まか</option>
                                    </select>
                                </div>
                            </div>
                        </details>
                        <!-- Forgetting (moved from Settings) -->
                        <details data-category="forgetting">
                            <summary><i data-lucide="eraser"></i> 忘却機構</summary>
                            <div class="details-body">
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-forgetting-enabled"
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-forgetting-enabled" class="chat-field-label" style="margin:0;cursor:pointer;">忘却機構を有効化</label>
                                </div>
                                <div>
                                    <div class="chat-field-label">忘却トリガー閾値</div>
                                    <input type="number" id="chat-forgetting-trigger-threshold" class="chat-field-input" min="1" step="1" value="100" />
                                </div>
                                <div>
                                    <div class="chat-field-label">減衰間隔（秒）</div>
                                    <input type="number" id="chat-forgetting-decay-interval-seconds" class="chat-field-input" min="60" step="1" value="86400" />
                                </div>
                                <div>
                                    <div style="display:flex;justify-content:space-between;">
                                        <span class="chat-field-label">最小強度</span>
                                        <span id="chat-forgetting-min-strength-val" style="font-size:0.72rem;color:var(--accent-purple);">0.10</span>
                                    </div>
                                    <input type="range" id="chat-forgetting-min-strength" class="chat-field-input" min="0" max="1" step="0.05" value="0.1"
                                        oninput="document.getElementById('chat-forgetting-min-strength-val').textContent=parseFloat(this.value).toFixed(2)"
                                        style="width:100%;accent-color:var(--accent-purple);" />
                                </div>
                                <div>
                                    <div style="display:flex;justify-content:space-between;">
                                        <span class="chat-field-label">忘却対象率</span>
                                        <span id="chat-forgetting-forget-ratio-val" style="font-size:0.72rem;color:var(--accent-purple);">0.20</span>
                                    </div>
                                    <input type="range" id="chat-forgetting-forget-ratio" class="chat-field-input" min="0" max="1" step="0.05" value="0.2"
                                        oninput="document.getElementById('chat-forgetting-forget-ratio-val').textContent=parseFloat(this.value).toFixed(2)"
                                        style="width:100%;accent-color:var(--accent-purple);" />
                                </div>
                                <div>
                                    <div style="display:flex;justify-content:space-between;">
                                        <span class="chat-field-label">忘却強度</span>
                                        <span id="chat-forgetting-forget-strength-val" style="font-size:0.72rem;color:var(--accent-purple);">0.50</span>
                                    </div>
                                    <input type="range" id="chat-forgetting-forget-strength" class="chat-field-input" min="0" max="1" step="0.05" value="0.5"
                                        oninput="document.getElementById('chat-forgetting-forget-strength-val').textContent=parseFloat(this.value).toFixed(2)"
                                        style="width:100%;accent-color:var(--accent-purple);" />
                                </div>
                            </div>
                        </details>
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
                        </details>
                    </div>
                    <!-- Sticky footer buttons -->
                    <div class="settings-footer">
                        <button class="chat-save-btn" onclick="saveChatConfig()" aria-label="チャット設定を保存"><i data-lucide="save"></i> 設定を保存</button>
                        <button class="chat-clear-btn" onclick="clearChatHistory()" aria-label="会話履歴をリセット"><i data-lucide="trash-2"></i> 会話をリセット</button>
                        <div id="chat-config-status" style="font-size:0.75rem; text-align:center; min-height:16px;"></div>
                    </div>
                </div>"""
