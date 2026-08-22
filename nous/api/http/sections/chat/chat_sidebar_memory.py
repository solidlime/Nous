"""Memory settings — extraction, reflection, mental models, weights, enrichment, forgetting."""


def _render_memory_section() -> str:
    """Memory extraction settings — auto-extract, models, memory tools."""
    return """
                        <!-- Memory extraction -->
                        <details data-category="memory">
                            <summary><i data-lucide="brain"></i> 記憶・抽出 <span class="chat-help-icon" data-category="memory" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
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
                                <div>
                                    <div class="chat-field-label">感情減衰半減期（時間）</div>
                                    <input type="number" id="chat-emotion-decay-half-life-hours" class="chat-field-input" min="0" step="0.5" value="24" />
                                </div>
                                <div>
                                    <div class="chat-field-label">感情減衰閾値</div>
                                    <input type="number" id="chat-emotion-decay-threshold" class="chat-field-input" min="0" step="0.01" value="0.005" />
                                </div>
                                <div>
                                    <div class="chat-field-label">中立感情閾値</div>
                                    <input type="number" id="chat-emotion-neutral-threshold" class="chat-field-input" min="0" step="0.01" value="0.01" />
                                </div>
                            </div>
                        </details>"""


def _render_reflection_section() -> str:
    """Reflection toggle, threshold, interval, session summary."""
    return """
                        <!-- Reflection -->
                        <details data-category="reflection">
                            <summary><i data-lucide="sparkles"></i> リフレクション <span class="chat-help-icon" data-category="reflection" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
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
                        </details>"""


def _render_mental_section() -> str:
    """Mental model extraction toggle and min samples."""
    return """
                        <!-- Mental Model -->
                        <details data-category="mental">
                            <summary><i data-lucide="puzzle"></i> メンタルモデル <span class="chat-help-icon" data-category="mental" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
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
                        </details>"""


def _render_weights_section() -> str:
    """Retrieval weight sliders — recency, importance, relevance, RRF k."""
    return """
                        <!-- Retrieval weights -->
                        <details data-category="weights">
                            <summary><i data-lucide="scale"></i> 検索重み <span class="chat-help-icon" data-category="weights" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
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
                        </details>"""


def _render_memory_enrichment_section() -> str:
    """Memory enrichment settings — auto-run, model, interval, advanced prompt template."""
    return """
                        <!-- Memory enrichment (moved from Settings) -->
                        <details data-category="memory_enrichment">
                            <summary><i data-lucide="layers"></i> 記憶エンリッチメント<span class="chat-help-icon" data-category="memory_enrichment" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <input type="checkbox" id="chat-memory-enrichment-enabled"
                                        style="width:15px;height:15px;accent-color:var(--accent-purple);cursor:pointer;" />
                                    <label for="chat-memory-enrichment-enabled" class="chat-field-label" style="margin:0;cursor:pointer;">記憶エンリッチメント有効</label>
                                </div>
                                <div>
                                    <div class="chat-field-label">モデル <span style="color:var(--text-muted);font-size:0.7rem;">（空白でチャットと同モデル）</span></div>
                                    <input type="text" id="chat-memory-enrichment-model" class="chat-field-input" placeholder="例: openai/gpt-4o-mini" />
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
                                <div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border-subtle);">
                                    <button type="button" class="chat-advanced-toggle" onclick="(function(btn){var b=btn.nextElementSibling;b.style.display=b.style.display==='none'?'':'none';})(this)" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:0.72rem;padding:2px 0;">▼ 詳細設定（プロンプトテンプレート）</button>
                                    <div style="display:none;margin-top:4px;">
                                        <div class="chat-field-label">プロンプトテンプレート</div>
                                        <textarea id="chat-memory-enrichment-prompt-template" class="chat-field-input" rows="4" style="resize:vertical;font-size:0.78rem;font-family:monospace;"></textarea>
                                    </div>
                                </div>
                            </div>
                        </details>"""


def _render_forgetting_section() -> str:
    """Forgetting mechanism — threshold, decay, strength sliders."""
    return """
                        <!-- Forgetting (moved from Settings) -->
                        <details data-category="forgetting">
                            <summary><i data-lucide="eraser"></i> 忘却機構<span class="chat-help-icon" data-category="forgetting" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
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
                        </details>"""
