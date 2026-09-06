"""Core settings — provider, model, context, system prompt."""


def _render_sidebar_header() -> str:
    """Sidebar opening div, close button, scroll container, sticky title."""
    return """
                <!-- Settings sidebar -->
                <div id="settings-panel" class="glass" style="margin:0; border-radius:0; border-left:1px solid var(--glass-border); padding:0;">
                    <!-- Mobile close button -->
                    <button id="settings-panel-close-btn" class="settings-panel-close" data-action="chat-toggle-settings" title="設定パネルを閉じる" aria-label="設定パネルを閉じる"><i data-lucide="x"></i></button>
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
                                    <div class="chat-field-label">モデル <span style="color:var(--accent-blue);font-size:0.7rem;">（空白でデフォルト）</span></div>
                                    <input type="text" id="chat-model" class="chat-field-input" placeholder="例: deepseek/deepseek-v4-flash-vision-exp" />
                                </div>
                                <div>
                                    <div class="chat-field-label">APIキー</div>
                                    <form data-password-form="chat-api-key" style="margin:0">
                                    <input type="password" id="chat-api-key" class="chat-field-input" placeholder="sk-..." autocomplete="off" />
                                    </form>
                                </div>
                                <div>
                                    <div class="chat-field-label">Base URL <span style="color:var(--accent-blue);font-size:0.7rem;">（必須）</span></div>
                                    <input type="text" id="chat-base-url" class="chat-field-input" placeholder="https://api.commandcode.ai/provider/v1" />
                                </div>
                                <div>
                                    <div class="chat-field-label chat-field-label-row">
                                        <span>Temperature</span>
                                        <span id="chat-temp-val" class="chat-field-value">0.7</span>
                                    </div>
                                    <input type="range" id="chat-temperature" class="chat-field-input" min="0" max="2" step="0.05" value="0.7"
                                        data-mirror="chat-temp-val" data-mirror-format="fixed2" />
                                </div>
                                <div class="chat-sub-block">
                                    <h4><i data-lucide="thermometer"></i> 動的温度調整</h4>
                                    <div class="chat-check-row">
                                        <input type="checkbox" id="chat-dynamic-temperature" class="chat-config-checkbox" checked
                                            data-toggle-target="chat-emotion-temperature-scale" data-toggle-mode="disabled" />
                                        <label for="chat-dynamic-temperature">動的温度調整を有効にする</label>
                                    </div>
                                    <div>
                                        <div class="chat-field-label chat-field-label-row">
                                            <span>感情温度スケール</span>
                                            <span id="chat-emotion-temp-scale-val" class="chat-field-value">0.20</span>
                                        </div>
                                        <input type="range" id="chat-emotion-temperature-scale" class="chat-field-input" min="0" max="1" step="0.05" value="0.2"
                                            data-mirror="chat-emotion-temp-scale-val" data-mirror-format="fixed2" />
                                    </div>
                                    <div>
                                        <div class="chat-field-label chat-field-label-row">
                                            <span>Top P</span>
                                            <span id="chat-top-p-val" class="chat-field-value">1.00</span>
                                        </div>
                                        <input type="range" id="chat-top-p" class="chat-field-input" min="0" max="1" step="0.05" value=""
                                            data-mirror="chat-top-p-val" data-mirror-format="topP" />
                                    </div>
                                </div>
                                <div class="chat-sub-block">
                                    <h4><i data-lucide="brain"></i> 思考モード（Reasoning）</h4>
                                    <div class="chat-check-row">
                                        <input type="checkbox" id="chat-reasoning-enabled" class="chat-config-checkbox"
                                            data-toggle-target="chat-reasoning-effort" data-toggle-mode="disabled" />
                                        <label for="chat-reasoning-enabled">推論（thinking）を有効にする</label>
                                    </div>
                                    <div>
                                        <div class="chat-field-label chat-field-label-row">
                                            <span>思考の深さ（Variant）</span>
                                            <span id="chat-reasoning-effort-val" class="chat-field-value">medium</span>
                                        </div>
                                        <input type="range" id="chat-reasoning-effort" class="chat-field-input" min="0" max="3" step="1" value="1" disabled
                                            data-mirror="chat-reasoning-effort-val" data-mirror-format="effort" />
                                    </div>
                                </div>
                                <div>
                                    <div class="chat-field-label">Max Tokens</div>
                                    <input type="number" id="chat-max-tokens" class="chat-field-input" min="1" max="131072" value="8192" />
                                </div>
                                <div>
                                    <div class="chat-field-label">言語</div>
                                    <select id="chat-language" class="chat-field-input">
                                        <option value="ja" selected>日本語</option>
                                        <option value="en">English</option>
                                        <option value="zh">中文</option>
                                        <option value="ko">한국어</option>
                                        <option value="auto">自動</option>
                                    </select>
                                </div>
                                <div class="chat-check-row">
                                    <input type="checkbox" id="chat-show-timestamps">
                                    <label for="chat-show-timestamps">メッセージにタイムスタンプを表示</label>
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
                                <details class="chat-subsection">
                                  <summary><i data-lucide="brain"></i> コンテキスト最適化</summary>
                                  <div style="padding-top:8px;">

                                  <div class="chat-field-label">保存メッセージ数</div>
                                  <input type="number" id="chat-stored-msgs" class="chat-field-input" value="200" min="2" max="2000" />
                                  <div class="chat-field-hint">SQLiteに保存する最大メッセージ数（セッション永続化用）</div>

                                  <div class="chat-field-label">トークン上限</div>
                                  <input type="number" id="chat-context-max-tokens" class="chat-field-input" value="" placeholder="自動（モデル判定）" min="1000" max="1000000" />
                                  <div class="chat-field-hint">空欄でモデルのコンテキストウィンドウを自動判定</div>

                                  <div class="chat-field-label">圧縮閾値 <span id="threshold-display">80%</span></div>
                                  <input type="range" id="chat-compression-threshold" class="chat-field-input" min="50" max="100" value="80" />

                                  <div class="chat-field-label">圧縮モード</div>
                                  <select id="chat-compression-mode" class="chat-field-input">
                                    <option value="auto">自動</option>
                                    <option value="light">軽度</option>
                                    <option value="normal">標準</option>
                                    <option value="aggressive">強力</option>
                                  </select>

                                  <div class="chat-field-label">完全保持ターン数</div>
                                  <input type="number" id="chat-keep-recent" class="chat-field-input" value="2" min="0" />
                                  <span class="setting-hint">AIが要約せず完全に保持する最新の会話ターン数です。</span>

                                  <div class="chat-field-label">記憶プリロード数</div>
                                  <input type="number" id="chat-memory-preload" class="chat-field-input" value="5" min="0" max="20" />
                                  <div class="chat-field-hint">systemプロンプトに含める関連記憶の数。0で全件オンデマンド検索</div>

                                  <div class="chat-field-label">記憶ダイジェスト数</div>
                                  <input type="number" id="chat-memory-digest" class="chat-field-input" value="5" min="0" max="20" />
                                  <div class="chat-field-hint">毎ターン最新 user 発言前に注入する最近の記憶の数。0で無効</div>

                                  <div class="chat-check-row">
                                    <input type="checkbox" id="chat-compress-system" checked>
                                    <label for="chat-compress-system">システムプロンプト圧縮</label>
                                  </div>
                                  <div class="chat-check-row">
                                    <input type="checkbox" id="chat-compress-history" checked>
                                    <label for="chat-compress-history">会話履歴圧縮</label>
                                  </div>
                                  <div class="chat-check-row">
                                    <input type="checkbox" id="chat-parallel-tools" checked>
                                    <label for="chat-parallel-tools">並列ツール実行</label>
                                  </div>
                                  <div class="chat-check-row">
                                    <input type="checkbox" id="chat-llm-summary" checked>
                                    <label for="chat-llm-summary">LLM要約圧縮</label>
                                  </div>
                                  <div class="chat-check-row">
                                    <input type="checkbox" id="chat-episode-search" checked>
                                    <label for="chat-episode-search">エピソード検索</label>
                                  </div>
                                  </div>
                                 </details>
                            </div>
                        </details>"""
