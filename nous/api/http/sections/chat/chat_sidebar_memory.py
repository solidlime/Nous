"""Memory settings — extraction, reflection, mental models, weights, enrichment, forgetting."""


def _render_memory_section() -> str:
    """Memory extraction settings — auto-extract, models, memory tools."""
    return """
                        <!-- Memory extraction -->
                        <details data-category="memory">
                            <summary><i data-lucide="brain"></i> 記憶・抽出 <span class="chat-help-icon" data-category="memory" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div class="chat-check-row">
                                    <input type="checkbox" id="chat-auto-extract" checked />
                                    <label for="chat-auto-extract">ターン毎に記憶を自動抽出 (Mem0方式)</label>
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
                                <div class="chat-check-row">
                                    <input type="checkbox" id="chat-enable-memory-tools" checked />
                                    <label for="chat-enable-memory-tools">LLMに組み込みメモリツールを渡す</label>
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
                                <div class="chat-check-row">
                                    <input type="checkbox" id="chat-reflection-enabled" checked />
                                    <label for="chat-reflection-enabled">リフレクション有効</label>
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
                                <div class="chat-check-row">
                                    <input type="checkbox" id="chat-session-summarize" checked />
                                    <label for="chat-session-summarize">セッション要約</label>
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
                                <div class="chat-check-row">
                                    <input type="checkbox" id="chat-mental-model-enabled" checked />
                                    <label for="chat-mental-model-enabled">メンタルモデル抽出を有効</label>
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
                                    <div class="chat-field-label chat-field-label-row">
                                        <span>鮮度</span>
                                        <span id="chat-recency-weight-val" class="chat-field-value">0.30</span>
                                    </div>
                                    <input type="range" id="chat-recency-weight" class="chat-field-input" min="0" max="1" step="0.05" value="0.3"
                                        data-mirror="chat-recency-weight-val" data-mirror-format="fixed2" />
                                </div>
                                <div>
                                    <div class="chat-field-label chat-field-label-row">
                                        <span>重要度</span>
                                        <span id="chat-importance-weight-val" class="chat-field-value">0.30</span>
                                    </div>
                                    <input type="range" id="chat-importance-weight" class="chat-field-input" min="0" max="1" step="0.05" value="0.3"
                                        data-mirror="chat-importance-weight-val" data-mirror-format="fixed2" />
                                </div>
                                <div>
                                    <div class="chat-field-label chat-field-label-row">
                                        <span>関連性</span>
                                        <span id="chat-relevance-weight-val" class="chat-field-value">0.40</span>
                                    </div>
                                    <input type="range" id="chat-relevance-weight" class="chat-field-input" min="0" max="1" step="0.05" value="0.4"
                                        data-mirror="chat-relevance-weight-val" data-mirror-format="fixed2" />
                                </div>
                                <div>
                                    <div class="chat-field-label chat-field-label-row">
                                        <span>RRF K値</span>
                                        <span id="chat-retrieval-rrf-k-val" class="chat-field-value">5</span>
                                    </div>
                                    <input type="range" id="chat-retrieval-rrf-k" class="chat-field-input" min="1" max="100" step="1" value="5"
                                        data-mirror="chat-retrieval-rrf-k-val" data-mirror-format="raw" />
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
                                <div class="chat-check-row">
                                    <input type="checkbox" id="chat-memory-enrichment-enabled" />
                                    <label for="chat-memory-enrichment-enabled">記憶エンリッチメント有効</label>
                                </div>
                                <div>
                                    <div class="chat-field-label">モデル <span style="color:var(--text-muted);font-size:0.7rem;">（空白でチャットと同モデル）</span></div>
                                    <input type="text" id="chat-memory-enrichment-model" class="chat-field-input" placeholder="例: openai/gpt-4o-mini" />
                                </div>
                                <div class="chat-check-row">
                                    <input type="checkbox" id="chat-memory-enrichment-auto-run" />
                                    <label for="chat-memory-enrichment-auto-run">自動実行</label>
                                </div>
                                <div>
                                    <div class="chat-field-label">実行間隔（分）</div>
                                    <input type="number" id="chat-memory-enrichment-interval" class="chat-field-input" min="1" step="1" value="60" />
                                </div>
                                <details class="chat-subsection">
                                    <summary>詳細設定（プロンプトテンプレート）</summary>
                                    <div style="padding-top:6px;">
                                        <div class="chat-field-label">プロンプトテンプレート</div>
                                        <textarea id="chat-memory-enrichment-prompt-template" class="chat-field-input" rows="4" style="resize:vertical;font-family:monospace;"></textarea>
                                    </div>
                                </details>
                            </div>
                        </details>"""


def _render_forgetting_section() -> str:
    """Forgetting mechanism — threshold, decay, strength sliders."""
    return """
                        <!-- Forgetting (moved from Settings) -->
                        <details data-category="forgetting">
                            <summary><i data-lucide="eraser"></i> 忘却機構<span class="chat-help-icon" data-category="forgetting" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div class="chat-check-row">
                                    <input type="checkbox" id="chat-forgetting-enabled" />
                                    <label for="chat-forgetting-enabled">忘却機構を有効化</label>
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
                                    <div class="chat-field-label chat-field-label-row">
                                        <span>最小強度</span>
                                        <span id="chat-forgetting-min-strength-val" class="chat-field-value">0.10</span>
                                    </div>
                                    <input type="range" id="chat-forgetting-min-strength" class="chat-field-input" min="0" max="1" step="0.05" value="0.1"
                                        data-mirror="chat-forgetting-min-strength-val" data-mirror-format="fixed2" />
                                </div>
                                <div>
                                    <div class="chat-field-label chat-field-label-row">
                                        <span>忘却対象率</span>
                                        <span id="chat-forgetting-forget-ratio-val" class="chat-field-value">0.20</span>
                                    </div>
                                    <input type="range" id="chat-forgetting-forget-ratio" class="chat-field-input" min="0" max="1" step="0.05" value="0.2"
                                        data-mirror="chat-forgetting-forget-ratio-val" data-mirror-format="fixed2" />
                                </div>
                                <div>
                                    <div class="chat-field-label chat-field-label-row">
                                        <span>忘却強度</span>
                                        <span id="chat-forgetting-forget-strength-val" class="chat-field-value">0.50</span>
                                    </div>
                                    <input type="range" id="chat-forgetting-forget-strength" class="chat-field-input" min="0" max="1" step="0.05" value="0.5"
                                        data-mirror="chat-forgetting-forget-strength-val" data-mirror-format="fixed2" />
                                </div>
                            </div>
                        </details>"""
