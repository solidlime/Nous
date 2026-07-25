"""Core settings — provider, model, context, system prompt."""


def _render_sidebar_header() -> str:
    """Sidebar opening div, close button, scroll container, sticky title."""
    return """
                <!-- Settings sidebar -->
                <div id="settings-panel" class="glass" style="margin:0; border-radius:0; border-left:1px solid var(--glass-border); padding:0;">
                    <!-- Mobile close button -->
                    <button id="settings-panel-close-btn" class="settings-panel-close" onclick="N.Chat.core.toggleSettings()" title="設定パネルを閉じる" aria-label="設定パネルを閉じる"><i data-lucide="x"></i></button>
                    <div class="settings-scroll-container">
                        <div style="position:sticky;top:0;z-index:10;background:var(--glass-bg);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);font-size:0.9rem;font-weight:600;color:var(--text-primary);padding:12px 0 8px;margin:0 -16px 8px;border-bottom:1px solid var(--glass-border);display:flex;align-items:center;gap:8px;">
                            <span style="font-size:1.1rem;margin-left:16px;"><i data-lucide="settings"></i></span>
                            <span>チャット設定</span>
                        </div>"""


def _render_core_section() -> str:
    """Provider, model, API key, temperature settings."""
    return """
                        <!-- Provider / Model / API -->
                        <details data-category="core" open>
                            <summary><i data-lucide="wrench"></i> 基本設定 <span class="chat-help-icon" data-category="core" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
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
                        </details>"""


def _render_context_section() -> str:
    """Context display, system prompt, compression, parallel tools."""
    return """
                        <!-- Context & System Prompt -->
                        <details data-category="context">
                            <summary><i data-lucide="message-circle"></i> コンテキスト <span class="chat-help-icon" data-category="context" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
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
                                   <div style="display:flex;align-items:center;gap:8px;margin:6px 0;">
                                     <input type="checkbox" id="chat-show-timestamps">
                                     <label for="chat-show-timestamps" style="font-size:0.8rem;">メッセージにタイムスタンプを表示</label>
                                   </div>
                                   </div>
                                 </details>
                            </div>
                        </details>"""
