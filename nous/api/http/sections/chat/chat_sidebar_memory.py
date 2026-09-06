"""Memory settings — extraction, reflection, mental models, weights, enrichment, forgetting."""


def _render_memory_section(children: str = "") -> str:
    """Memory intake group — extraction fields + nested child accordions.

    children: .chat-subsection markup (auto-capture, mental model,
    reflection) — everything that WRITES memories into the store.
    """
    return f"""
                        <!-- Memory extraction (intake group) -->
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
                                {children}
                            </div>
                        </details>"""


def _render_reflection_section() -> str:
    """Reflection settings — nested child of the 記憶・抽出 group.

    Content keeps class="details-body": chat-memory-panel.js injects the
    発火表示数 field into `details[data-category="reflection"] .details-body`.
    """
    return """
                                <!-- Reflection (child of memory group) -->
                                <details class="chat-subsection" data-category="reflection">
                                    <summary>リフレクション <span class="chat-help-icon" data-category="reflection" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
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
    """Mental model settings — nested child of the 記憶・抽出 group."""
    return """
                                <!-- Mental Model (child of memory group) -->
                                <details class="chat-subsection" data-category="mental">
                                    <summary>メンタルモデル <span class="chat-help-icon" data-category="mental" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
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


_BRAIN_HELP = {
    "enabled": "LLM による記憶エンリッチメントを有効化します。オフにすると自動評価も新規性ゲートも実行されません。",
    "auto_run": "定期実行（REM 相当）のオン/オフ。睡眠中の記憶再生のように、新しい記憶をバックグラウンドで再処理します。",
    "interval": "記憶強化ループの実行間隔（秒）。REM 睡眠の短い周期に相当します。",
    "batch_limit": "1 周で処理する記憶の上限。一度に大量に再処理すると記憶が乱れるため、小分けにします。",
    "novelty_sim": "海馬-VTA ループのドーパミンゲート。既存記憶との類似がこの値より低いほど「新規」と判定され、長期記憶への定着が強まります。",
    "novelty_importance": "新規性判定の対象になる重要度のしきい値。重要な記憶だけを新規性ゲートに通します。",
    "novelty_multiplier": "新規と判定された記憶の初期安定度の倍率。新規性ブーストは作成後 1 回だけ与えられます（長期増強）。",
    "emotion_gain": "感情が強い記憶ほど想起時に強化されやすくなる係数（扁桃体モデル）。上限は内部で固定されます。",
    "rif_rho": "想起のたびに、手がかりを共有する競合記憶がわずかに抑制されます（検索誘発性忘却）。",
    "separation": "記憶同士のシナプス結合を作る類似度のしきい値。高いほど似た記憶だけが結合し、pattern separation が強まります（将来実装。類似度ソースが未接続のため現在は未使用）。",
    "flash": "シナプス発火イベントを記憶グラフ上で発光表示します。",
    "llm_dedicated": "OFF ではチャット設定と同じ LLM を脳シミュレーターに使います。ON にすると専用の provider / model / API キーを設定できます。",
    "llm_provider": "脳シミュレーター専用 LLM のプロバイダ。空欄なら従来の記憶強化設定を引き継ぎます。",
    "llm_model": "専用 LLM のモデル名。空欄なら従来の記憶強化設定を引き継ぎます。",
    "llm_base_url": "専用 LLM の API エンドポイント。空欄なら従来の記憶強化設定を引き継ぎます。",
    "llm_api_key": "専用 LLM の API キー。空欄でプロバイダがチャットと一致する場合はチャットのキーをフォールバックに使います。",
}


def _brain_help(key: str) -> str:
    """? マークホバー（title 属性）— 脳神経科学由来の説明文。"""
    text = _BRAIN_HELP[key].replace('"', "'")
    return f'<span class="chat-help-tip" title="{text}" aria-label="説明" tabindex="0">?</span>'


def _render_brain_simulation_section(children: str = "") -> str:
    """脳シミュレーション設定 — 旧 memory_enrichment セクションを吸収・置換。

    children: 忘却機構など、保存済み記憶を「鍛える/減衰させる」系の
    ネスト subsection を想起と忘却の後に差し込む。
    関数名は chat_sidebar.py の import 互換のため維持（chat_sidebar.py は
    lane3 の所有外）。実体は brain_simulation カテゴリの 1 セクション。
    """
    help_ = _brain_help
    return f"""
                        <!-- Brain simulation (absorbs memory enrichment) -->
                        <details data-category="brain_simulation">
                            <summary><i data-lucide="brain-circuit"></i> 脳シミュレーション <span class="chat-help-icon" data-category="brain_simulation" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <details class="chat-subsection">
                                    <summary>記憶強化（REM）</summary>
                                    <div style="padding-top:6px;">
                                        <div class="chat-check-row">
                                            <input type="checkbox" id="chat-memory-enrichment-enabled" />
                                            <label for="chat-memory-enrichment-enabled">記憶エンリッチメント有効 {help_("enabled")}</label>
                                        </div>
                                        <div class="chat-check-row">
                                            <input type="checkbox" id="chat-brain-auto-run" />
                                            <label for="chat-brain-auto-run">自動実行 {help_("auto_run")}</label>
                                        </div>
                                        <div>
                                            <div class="chat-field-label">実行間隔（秒）{help_("interval")}</div>
                                            <input type="number" id="chat-brain-enrich-interval" class="chat-field-input" min="10" step="10" value="60" />
                                        </div>
                                        <div>
                                            <div class="chat-field-label">1 周あたり上限件数 {help_("batch_limit")}</div>
                                            <input type="number" id="chat-brain-batch-limit" class="chat-field-input" min="1" max="50" step="1" value="5" />
                                        </div>
                                    </div>
                                </details>
                                <details class="chat-subsection">
                                    <summary>専用 LLM</summary>
                                    <div style="padding-top:6px;">
                                        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
                                            <span class="chat-field-label" style="margin:0;">脳シミュレーター専用 LLM を使う {help_("llm_dedicated")}</span>
                                            <label class="toggle-switch">
                                                <input type="checkbox" id="chat-brain-llm-dedicated" data-action="brain-llm-toggle" />
                                                <span class="toggle-slider"></span>
                                            </label>
                                        </div>
                                        <div id="chat-brain-llm-fields" class="settings-body-hidden">
                                            <div>
                                                <div class="chat-field-label">Provider {help_("llm_provider")}</div>
                                                <input type="text" id="chat-brain-llm-provider" class="chat-field-input" placeholder="例: openai" />
                                            </div>
                                            <div>
                                                <div class="chat-field-label">Model {help_("llm_model")}</div>
                                                <input type="text" id="chat-brain-llm-model" class="chat-field-input" placeholder="例: gpt-4o-mini" />
                                            </div>
                                            <div>
                                                <div class="chat-field-label">Base URL {help_("llm_base_url")}</div>
                                                <input type="text" id="chat-brain-llm-base-url" class="chat-field-input" placeholder="https://api.example.com/v1" />
                                            </div>
                                            <div>
                                                <div class="chat-field-label">APIキー {help_("llm_api_key")}</div>
                                                <form data-password-form="chat-brain-llm-api-key" style="margin:0">
                                                <input type="password" id="chat-brain-llm-api-key" class="chat-field-input" placeholder="sk-..." autocomplete="off" />
                                                </form>
                                            </div>
                                        </div>
                                    </div>
                                </details>
                                <details class="chat-subsection">
                                    <summary>学習ゲート</summary>
                                    <div style="padding-top:6px;">
                                        <div>
                                            <div class="chat-field-label">新規性 類似度しきい値 {help_("novelty_sim")}</div>
                                            <input type="number" id="chat-brain-novelty-sim" class="chat-field-input" min="0" max="1" step="0.01" value="0.75" />
                                        </div>
                                        <div>
                                            <div class="chat-field-label">新規性 重要度しきい値 {help_("novelty_importance")}</div>
                                            <input type="number" id="chat-brain-novelty-importance" class="chat-field-input" min="0" max="1" step="0.01" value="0.6" />
                                        </div>
                                        <div>
                                            <div class="chat-field-label">新規性 ブースト倍率 {help_("novelty_multiplier")}</div>
                                            <input type="number" id="chat-brain-novelty-multiplier" class="chat-field-input" min="1" max="5" step="0.1" value="2.0" />
                                        </div>
                                        <div>
                                            <div class="chat-field-label">感情 gain 係数 k {help_("emotion_gain")}</div>
                                            <input type="number" id="chat-brain-emotion-gain-k" class="chat-field-input" min="0" max="1" step="0.05" value="0.5" />
                                        </div>
                                    </div>
                                </details>
                                <details class="chat-subsection">
                                    <summary>想起と忘却</summary>
                                    <div style="padding-top:6px;">
                                        <div>
                                            <div class="chat-field-label">競合抑制係数 ρ {help_("rif_rho")}</div>
                                            <input type="number" id="chat-brain-rif-rho" class="chat-field-input" min="0" max="0.5" step="0.01" value="0.05" />
                                        </div>
                                        <div>
                                            <div class="chat-field-label">リンク分離しきい値 {help_("separation")}</div>
                                            <!-- 将来実装: upsert_link(similarity=) の類似度ソース未接線のため休止中 -->
                                            <input type="number" id="chat-brain-separation-threshold" class="chat-field-input" min="0.5" max="1" step="0.01" value="0.75" disabled />
                                        </div>
                                    </div>
                                </details>
                                {children}
                                <details class="chat-subsection">
                                    <summary>可視化</summary>
                                    <div style="padding-top:6px;">
                                        <div class="chat-check-row">
                                            <input type="checkbox" id="chat-brain-graph-flash" checked />
                                            <label for="chat-brain-graph-flash">グラフ発光 {help_("flash")}</label>
                                        </div>
                                    </div>
                                </details>
                            </div>
                        </details>"""


def _render_forgetting_section() -> str:
    """Forgetting mechanism — nested child of the 脳シミュレーション group.

    時間減衰ベースの忘却ワーカー設定。脳の「想起と忘却」(RIF) と同じ
    忘却系なので brain_simulation 配下にまとめる。
    """
    return """
                                <!-- Forgetting (child of brain group, moved from Settings) -->
                                <details class="chat-subsection" data-category="forgetting">
                                    <summary>忘却機構 <span class="chat-help-icon" data-category="forgetting" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
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
