"""Memory settings — extraction, reflection, mental models, weights, forgetting."""


def _render_memory_section(children: str = "") -> str:
    """Memory intake group — extraction fields + nested child accordions.

    children: .chat-subsection markup (mental model,
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
                                        <div>
                                            <div class="chat-field-label">実行間隔 (サイクル)</div>
                                            <input type="number" id="chat-reflection-interval" class="chat-field-input"
                                                min="1" max="168" step="1" value="24" />
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
                            </div>
                        </details>"""


_BRAIN_HELP = {
    "brain_reasoning": "脳側の呼び出し（内省）で推論（reasoning）を有効化します。OFF でも未設定（null）なら解決済みLLM設定に従います（専用OFFなら会話用LLMの設定。設定ファイル直接編集時のみ null を指定できます）。ON で brain_reasoning_effort を強制使用、OFF（明示の false）で推論なし。OpenRouter 経由で推論だけが予算を使い切る事故対策として、明示 OFF では推論を無効化します。",
    "brain_max_tokens": "脳側呼び出し（内省）のトークン上限。0 で解決済みLLM設定に従います（専用OFFなら会話用の値、ONなら脳側既定）。明示設定時（256〜32768）は全モードで上書きし、reasoning を有効化した場合は推論分を賄うため自動で嵩上げされます（low 4096 / medium 5120 / high 9216 / max 17408）。reasoning 有効時、保存時に実効値へ引き上げる場合があります（0 のまま保存した場合は実行時に解決されます）。手動でそれ以上に設定した場合は引き下げません。",
    "emotion_gain": "感情が強い記憶ほど想起時に強化されやすくなる係数（扁桃体モデル）。上限は内部で固定されます。",
    "rif_rho": "想起のたびに、手がかりを共有する競合記憶がわずかに抑制されます（検索誘発性忘却）。",
    "reflection_penalty": "リフレクション系の記憶が検索に引っかかりやすすぎないよう、想起スコアを押し下げる強さ。値が大きいほど思い出しにくくなります（思い出しにくさの踏ん張り）。",
    "reflection_injection_sim": "リフレクションを文脈に注入するときの類似度ゲート。この値より似ていない記憶は注入されません（無関係な思い出しの防止）。",
    "reflection_injection_margin": "注入候補の選択を、候補集合内の最良値からの差（マージン）でも許容します。小さいほど最良に近い候補だけが注入されます（0 で類似度ゲートのみ）。",
    "separation": "記憶同士のシナプス結合を作る類似度のしきい値。高いほど似た記憶だけが結合し、pattern separation が強まります（将来実装。類似度ソースが未接続のため現在は未使用）。",
    "flash": "シナプス発火イベントを記憶グラフ上で発光表示します。",
    "llm_dedicated": "OFF ではチャット設定と同じ LLM を脳シミュレーターに使います。ON にすると専用の provider / model / API キーを設定できます。",
    "llm_provider": "脳シミュレーター専用 LLM のプロバイダ。空欄なら従来の記憶強化設定を引き継ぎます。",
    "llm_model": "専用 LLM のモデル名。空欄なら従来の記憶強化設定を引き継ぎます。",
    "llm_base_url": "専用 LLM の API エンドポイント。空欄なら従来の記憶強化設定を引き継ぎます。",
    "llm_api_key": "専用 LLM の API キー。空欄でプロバイダがチャットと一致する場合はチャットのキーをフォールバックに使います。",
    "decision_enabled": "検索候補を LLM に一括判定させ、閾値未満の候補を除外します（Jev 型判定ゲート）。OFF のときは現行どおり候補をそのまま返します。",
    "decision_model": "判定に使うモデル名。空欄なら脳シミュレーターのデフォルト LLM を使います。",
    "decision_threshold": "候補を採用する確率のしきい値。値が高いほど厳しく絞り込まれます。",
    "decision_max_hops": "1 で単発検索。2 以上で採用候補からクエリを合成して再検索します（multi-hop）。",
    "decision_time_weight": "判定ゲート通過後の並べ替えに時間減衰を掛けます。0 より大きければ値に依らず全て同じ強さ（=有効）で、0 で無効。採否は変えません（表示される倍率は floor 適用後の実効値）。判定ゲートと Judge が有効な場合のみ作用します。",
}


def _brain_help(key: str) -> str:
    """? マークホバー（title 属性）— 脳神経科学由来の説明文。"""
    text = _BRAIN_HELP[key].replace('"', "'")
    return f'<span class="chat-help-tip" title="{text}" aria-label="説明" tabindex="0">?</span>'


def _render_brain_simulation_section(children: str = "") -> str:
    """脳シミュレーション設定 — 旧 memory_enrichment セクションの後継。

    children: 忘却機構など、保存済み記憶を「鍛える/減衰させる」系の
    ネスト subsection を想起と忘却の後に差し込む。
    関数名は chat_sidebar.py の import 互換のため維持（chat_sidebar.py は
    lane3 の所有外）。実体は brain_simulation カテゴリの 1 セクション。
    """
    help_ = _brain_help
    return f"""
                        <!-- Brain simulation -->
                        <details data-category="brain_simulation">
                            <summary><i data-lucide="brain-circuit"></i> 脳シミュレーション <span class="chat-help-icon" data-category="brain_simulation" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <details class="chat-subsection">
                                    <summary>LLM</summary>
                                    <div style="padding-top:6px;">
                                        <div class="chat-check-row">
                                            <input type="checkbox" id="chat-brain-reasoning" />
                                            <label for="chat-brain-reasoning">脳側 reasoning {help_("brain_reasoning")}</label>
                                        </div>
                                        <div>
                                            <div class="chat-field-label">推論 effort {help_("brain_reasoning")}</div>
                                            <select id="chat-brain-reasoning-effort" class="chat-field-input">
                                                <option value="low">low</option>
                                                <option value="medium" selected>medium</option>
                                                <option value="high">high</option>
                                                <option value="max">max</option>
                                            </select>
                                        </div>
                                        <div>
                                            <div class="chat-field-label">脳側 max tokens {help_("brain_max_tokens")}</div>
                                            <input type="number" id="chat-brain-max-tokens" class="chat-field-input" min="0" max="32768" step="256" placeholder="0 = 継承" value="0" />
                                        </div>
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
                                        <div>
                                            <div class="chat-field-label">リフレクション降格 {help_("reflection_penalty")}</div>
                                            <input type="number" id="chat-brain-reflection-retrieval-penalty" class="chat-field-input" min="0.1" max="1" step="0.05" value="0.5" />
                                        </div>
                                        <div>
                                            <div class="chat-field-label">リフレクション注入 類似度ゲート {help_("reflection_injection_sim")}</div>
                                            <input type="number" id="chat-brain-reflection-injection-min-similarity" class="chat-field-input" min="0" max="1" step="0.05" value="0.45" />
                                        </div>
                                        <div>
                                            <div class="chat-field-label">リフレクション注入 相対マージン {help_("reflection_injection_margin")}</div>
                                            <input type="number" id="chat-brain-reflection-injection-margin" class="chat-field-input" min="0" max="1" step="0.01" value="0.08" />
                                        </div>
                                    </div>
                                </details>
                                <details class="chat-subsection">
                                    <summary>判定ゲート（Jev型）</summary>
                                    <div style="padding-top:6px;">
                                        <div class="chat-check-row">
                                            <input type="checkbox" id="chat-brain-decision-enabled" />
                                            <label for="chat-brain-decision-enabled">判定ゲートを有効 {help_("decision_enabled")}</label>
                                        </div>
                                        <div>
                                            <div class="chat-field-label">判定モデル {help_("decision_model")}</div>
                                            <input type="text" id="chat-brain-decision-model" class="chat-field-input" placeholder="空 = デフォルト" />
                                        </div>
                                        <div>
                                            <div class="chat-field-label chat-field-label-row">
                                                <span>採用しきい値 {help_("decision_threshold")}</span>
                                                <span id="chat-brain-decision-threshold-val" class="chat-field-value">0.55</span>
                                            </div>
                                            <input type="range" id="chat-brain-decision-threshold" class="chat-field-input" min="0" max="1" step="0.05" value="0.55"
                                                data-mirror="chat-brain-decision-threshold-val" data-mirror-format="fixed2" />
                                        </div>
                                        <div>
                                            <div class="chat-field-label">最大ホップ数 {help_("decision_max_hops")}</div>
                                            <select id="chat-brain-decision-max-hops" class="chat-field-input">
                                                <option value="1" selected>1</option>
                                                <option value="2">2</option>
                                                <option value="3">3</option>
                                                <option value="4">4</option>
                                                <option value="5">5</option>
                                            </select>
                                        </div>
                                        <div class="chat-check-row">
                                            <input type="checkbox" id="chat-brain-decision-time-weight" />
                                            <label for="chat-brain-decision-time-weight">時間減衰を有効 {help_("decision_time_weight")}</label>
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
                                    </div>
                                </details>"""
