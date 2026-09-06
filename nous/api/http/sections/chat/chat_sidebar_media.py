"""Media settings — image generation (ComfyUI), voice/TTS (Irodori)."""


def _render_image_section() -> str:
    """Image generation settings — ComfyUI URL, resolution, presets, workflow template."""
    return """
                        <!-- 画像生成 -->
                        <details data-category="image" id="chat-image-section">
                            <summary><i data-lucide="image"></i> 画像生成 <span class="chat-help-icon" data-category="image" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
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
                                    <!-- 自画像生成プロンプト -->
                                    <div>
                                        <div class="chat-field-label">自画像プロンプト <span style="color:var(--text-muted);font-size:0.7rem;">（キャラの外見タグ・LoRAトリガーワード等）</span></div>
                                        <textarea id="chat-image-gen-self-portrait-prompt" class="chat-field-input" placeholder="キャラ外見タグ（例: 1girl, solo, purple eyes, short white hair, witch hat, holding ornate key-shaped staff）" rows="3" style="width:100%;resize:vertical;font-size:0.78rem;"></textarea>
                                    </div>
                                    <div>
                                        <div class="chat-field-label">ネガティブプロンプト <span style="font-weight:300;color:var(--text-dim);">(低画質・崩れ除外タグ)</span></div>
                                        <textarea id="chat-image-gen-negative-prompt" class="chat-field-input" style="min-height:48px;width:100%;" placeholder="lowres, bad anatomy, bad hands, text, error"></textarea>
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
                                        <div class="chat-field-label">最大解像度（LLMが指定できる上限）</div>
                                        <div style="display:flex;gap:8px;align-items:center;">
                                            <span style="font-size:0.78rem;">W</span>
                                            <input type="number" id="chat-image-gen-max-width" class="chat-field-input" value="1200" min="64" max="4096" step="64" style="width:90px;" />
                                            <span style="font-size:0.78rem;">H</span>
                                            <input type="number" id="chat-image-gen-max-height" class="chat-field-input" value="1200" min="64" max="4096" step="64" style="width:90px;" />
                                        </div>
                                    </div>
                                    <div>
                                        <div class="chat-field-label">プリセット解像度 <span style="font-weight:300;color:var(--text-dim);">(LLMが選ぶ解像度プリセット)</span></div>
                                        <div class="chat-preset-grid">
                                            <span></span>
                                            <span style="text-align:center;color:var(--text-dim);">Large</span>
                                            <span style="text-align:center;color:var(--text-dim);">Medium</span>
                                            <span style="text-align:center;color:var(--text-dim);">Small</span>
                                            <span style="color:var(--text-dim);">縦長</span>
                                            <input type="text" id="chat-image-gen-preset-portrait_large" class="chat-field-input" value="832x1216" style="width:100%;" />
                                            <input type="text" id="chat-image-gen-preset-portrait_medium" class="chat-field-input" value="768x1024" style="width:100%;" />
                                            <input type="text" id="chat-image-gen-preset-portrait_small" class="chat-field-input" value="576x768" style="width:100%;" />
                                            <span style="color:var(--text-dim);">横長</span>
                                            <input type="text" id="chat-image-gen-preset-landscape_large" class="chat-field-input" value="1216x832" style="width:100%;" />
                                            <input type="text" id="chat-image-gen-preset-landscape_medium" class="chat-field-input" value="1024x768" style="width:100%;" />
                                            <input type="text" id="chat-image-gen-preset-landscape_small" class="chat-field-input" value="768x576" style="width:100%;" />
                                            <span style="color:var(--text-dim);">正方形</span>
                                            <input type="text" id="chat-image-gen-preset-square_large" class="chat-field-input" value="1024x1024" style="width:100%;" />
                                            <input type="text" id="chat-image-gen-preset-square_medium" class="chat-field-input" value="768x768" style="width:100%;" />
                                            <input type="text" id="chat-image-gen-preset-square_small" class="chat-field-input" value="512x512" style="width:100%;" />
                                        </div>
                                        <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
                                            <span class="chat-field-label">デフォルト</span>
                                            <select id="chat-image-gen-default-preset" class="chat-field-input" style="flex:1;font-size:0.78rem;">
                                                <option value="portrait_large">portrait_large</option>
                                                <option value="portrait_medium">portrait_medium</option>
                                                <option value="portrait_small">portrait_small</option>
                                                <option value="landscape_large">landscape_large</option>
                                                <option value="landscape_medium">landscape_medium</option>
                                                <option value="landscape_small">landscape_small</option>
                                                <option value="square_large">square_large</option>
                                                <option value="square_medium" selected>square_medium</option>
                                                <option value="square_small">square_small</option>
                                            </select>
                                        </div>
                                    </div>
                                    <!-- workflow source selector -->
                                    <div style="margin-top:8px;">
                                        <div class="chat-field-label">ワークフロー取得元</div>
                                        <select id="chat-image-gen-workflow-source" class="chat-field-input" style="width:100%;">
                                            <option value="local" selected>Nous サーバー（data/workflows/）</option>
                                            <option value="comfyui">ComfyUI サーバー（user/default/workflows/）</option>
                                        </select>
                                    </div>
                                    <!-- workflow name (comfyui source) -->
                                    <div style="margin-top:8px;">
                                        <div class="chat-field-label">ワークフロー名（ComfyUI 側のファイル名）</div>
                                        <input type="text" id="chat-image-gen-workflow-name" class="chat-field-input"
                                            placeholder="例: Anima_T2I_Turbo_Aesthetic.json"
                                             style="width:100%;" />
                                    </div>
                                    <!-- workflow template path -->
                                    <div style="margin-top:8px;">
                                        <div class="chat-field-label">ワークフローテンプレート（必須・Nous サーバー側のパス）</div>
                                        <input type="text" id="chat-image-gen-template" class="chat-field-input"
                                            placeholder="例: /data/workflows/pony_ipadapter.json"
                                             style="width:100%;" />
                                    </div>
                                    <!-- 構図プリフィックス -->
                                    <details class="chat-subsection">
                                        <summary>構図プリフィックス</summary>
                                        <div style="padding-top:6px;display:flex;flex-direction:column;gap:8px;">
                                            <div>
                                                <div class="chat-field-label">全身</div>
                                                <input type="text" id="chat-image-gen-full-body-prefix" class="chat-field-input" value="full body, standing, pov, " />
                                            </div>
                                            <div>
                                                <div class="chat-field-label">ポートレート</div>
                                                <input type="text" id="chat-image-gen-portrait-prefix" class="chat-field-input" value="upper body, portrait, pov, " />
                                            </div>
                                            <div>
                                                <div class="chat-field-label">自撮り</div>
                                                <input type="text" id="chat-image-gen-selfie-prefix" class="chat-field-input" value="selfie, from below, mirror selfie, " />
                                            </div>
                                            <div>
                                                <div class="chat-field-label">風景・シーン</div>
                                                <input type="text" id="chat-image-gen-scene-prefix" class="chat-field-input" value="environment shot, full body, " />
                                            </div>
                                        </div>
                                    </details>
                                    <!-- Image caption (non-vision providers) -->
                                    <details class="chat-subsection">
                                        <summary>画像キャプション（非ビジョンモデル用）</summary>
                                        <div style="padding-top:6px;display:flex;flex-direction:column;gap:8px;">
                                            <div class="chat-check-row">
                                                <input type="checkbox" id="chat-image-caption-enabled" checked />
                                                <label for="chat-image-caption-enabled">画像キャプション生成を有効化</label>
                                            </div>
                                            <div>
                                                <div class="chat-field-label">プロバイダー</div>
                                                <input type="text" id="chat-image-caption-provider" class="chat-field-input" value="openai_compat" />
                                            </div>
                                            <div>
                                                <div class="chat-field-label">モデル</div>
                                                <input type="text" id="chat-image-caption-model" class="chat-field-input" placeholder="例: gpt-4o-mini" />
                                            </div>
                                            <div>
                                                <div class="chat-field-label">APIキー</div>
                                                <form data-password-form="chat-image-caption-api-key" style="margin:0">
                                                <input type="password" id="chat-image-caption-api-key" class="chat-field-input" autocomplete="off" />
                                                </form>
                                            </div>
                                            <div>
                                                <div class="chat-field-label">Base URL</div>
                                                <input type="text" id="chat-image-caption-base-url" class="chat-field-input" />
                                            </div>
                                        </div>
                                    </details>
                                    <div id="chat-image-test-result" style="display:none;margin-bottom:8px;text-align:center;">
                                        <img id="chat-image-test-img" alt="テスト生成結果"
                                            style="max-width:100%;max-height:240px;border-radius:8px;object-fit:contain;" />
                                    </div>
                                    <div class="chat-test-row">
                                        <button type="button" class="chat-test-btn" data-action="chat-test-image"><i data-lucide="play"></i> テスト生成</button>
                                        <span id="chat-image-test-status" class="chat-test-status"></span>
                                    </div>
                                </div>
                            </div>
                        </details>"""


def _render_voice_section() -> str:
    """Voice/TTS settings — Irodori server, voice model, advanced params."""
    return """
                        <!-- Voice / TTS (TE04) -->
                        <details data-category="voice" id="chat-voice-section">
                            <summary><i data-lucide="volume-2"></i> 音声 <span class="chat-help-icon" data-category="voice" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
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
                                    <div>
                                        <div class="chat-field-label">感情の反映</div>
                                        <div style="display:flex;flex-direction:column;gap:4px;margin-top:4px;">
                                            <label class="chat-inline-check">
                                                <input type="radio" name="chat-voice-emotion-mode" value="off"
                                                    data-toggle-target="chat-irodori-caption-llm-model-wrap" data-toggle-mode="display" data-toggle-value="none" />
                                                反映しない</label>
                                            <label class="chat-inline-check">
                                                <input type="radio" name="chat-voice-emotion-mode" value="anchor" checked
                                                    data-toggle-target="chat-irodori-caption-llm-model-wrap" data-toggle-mode="display" data-toggle-value="none" />
                                                反映する（標準）</label>
                                            <label class="chat-inline-check">
                                                <input type="radio" name="chat-voice-emotion-mode" value="llm"
                                                    data-toggle-target="chat-irodori-caption-llm-model-wrap" data-toggle-mode="display" data-toggle-value="block" />
                                                反映する＋LLMで磨く（少し遅くなります）</label>
                                        </div>
                                    </div>
                                    <div class="chat-check-row">
                                        <input type="checkbox" id="chat-voice-auto-play" />
                                        <label for="chat-voice-auto-play">応答を自動再生</label>
                                    </div>
                                    <div class="chat-check-row">
                                        <input type="checkbox" id="chat-voice-streaming" checked />
                                        <label for="chat-voice-streaming">文ごと逐次再生（ストリーミング）</label>
                                    </div>
                                    <!-- Voice volume -->
                                    <div>
                                        <div class="chat-field-label chat-field-label-row">
                                            <span>音量</span>
                                            <span id="chat-voice-volume-val" class="chat-field-value">100%</span>
                                        </div>
                                        <input type="range" id="chat-voice-volume" class="chat-field-input"
                                            min="0.0" max="1.0" step="0.05" value="1.0"
                                            data-mirror="chat-voice-volume-val" data-mirror-format="percent" />
                                    </div>
                                    <!-- Voice speed -->
                                    <div>
                                        <div class="chat-field-label chat-field-label-row">
                                            <span>話速</span>
                                            <span id="chat-voice-speed-val" class="chat-field-value">1.0x</span>
                                        </div>
                                        <input type="range" id="chat-voice-speed" class="chat-field-input"
                                            min="0.25" max="4.0" step="0.05" value="1.0"
                                            data-mirror="chat-voice-speed-val" data-mirror-format="fixed2" data-mirror-suffix="x" />
                                    </div>
                                    <!-- Irodori advanced params -->
                                    <details class="chat-subsection">
                                        <summary>詳細設定</summary>
                                        <div style="display:flex;flex-direction:column;gap:10px;padding-top:6px;">
                                            <!-- num_steps: range 10-50, step 1, default 30 -->
                                            <div>
                                                <div class="chat-field-label chat-field-label-row">
                                                    <span>推論ステップ数</span>
                                                    <span id="chat-irodori-num-steps-val" class="chat-field-value">30</span>
                                                </div>
                                                <input type="range" id="chat-irodori-num-steps" class="chat-field-input"
                                                    min="10" max="50" step="1" value="30"
                                                    data-mirror="chat-irodori-num-steps-val" data-mirror-format="raw" />
                                            </div>
                                            <!-- cfg_scale_text: range 1.0-5.0, step 0.1, default 3.2 -->
                                            <div>
                                                <div class="chat-field-label chat-field-label-row">
                                                    <span>テキスト忠実度</span>
                                                    <span id="chat-irodori-cfg-text-val" class="chat-field-value">3.2</span>
                                                </div>
                                                <input type="range" id="chat-irodori-cfg-scale-text" class="chat-field-input"
                                                    min="1.0" max="5.0" step="0.1" value="3.2"
                                                    data-mirror="chat-irodori-cfg-text-val" data-mirror-format="fixed1" />
                                            </div>
                                            <!-- cfg_scale_speaker: range 1.0-8.0, step 0.1, default 5.0 -->
                                            <div>
                                                <div class="chat-field-label chat-field-label-row">
                                                    <span>話者再現度</span>
                                                    <span id="chat-irodori-cfg-speaker-val" class="chat-field-value">5.0</span>
                                                </div>
                                                <input type="range" id="chat-irodori-cfg-scale-speaker" class="chat-field-input"
                                                    min="1.0" max="8.0" step="0.1" value="5.0"
                                                    data-mirror="chat-irodori-cfg-speaker-val" data-mirror-format="fixed1" />
                                            </div>
                                            <!-- cfg_scale_caption: range 1.0-8.0, step 0.1, default 4.2 -->
                                            <div>
                                                <div class="chat-field-label chat-field-label-row">
                                                    <span>感情・スタイル強度</span>
                                                    <span id="chat-irodori-cfg-caption-val" class="chat-field-value">4.2</span>
                                                </div>
                                                <input type="range" id="chat-irodori-cfg-scale-caption" class="chat-field-input"
                                                    min="1.0" max="8.0" step="0.1" value="4.2"
                                                    data-mirror="chat-irodori-cfg-caption-val" data-mirror-format="fixed1" />
                                            </div>
                                            <!-- chunk_min_chars: range 30-200, step 5, default 85 -->
                                            <div>
                                                <div class="chat-field-label chat-field-label-row">
                                                    <span>最小チャンク文字数</span>
                                                    <span id="chat-irodori-chunk-min-val" class="chat-field-value">85</span>
                                                </div>
                                                <input type="range" id="chat-irodori-chunk-min-chars" class="chat-field-input"
                                                    min="30" max="200" step="5" value="85"
                                                    data-mirror="chat-irodori-chunk-min-val" data-mirror-format="raw" />
                                            </div>
                                            <!-- seed: number input, 0=random -->
                                            <div>
                                                <div class="chat-field-label">乱数シード（0=ランダム）</div>
                                                <input type="number" id="chat-irodori-seed" class="chat-field-input"
                                                    value="0" min="0" />
                                            </div>
                                            <!-- LLM caption model (「反映する＋LLMで磨く」のときのみ表示) -->
                                            <div id="chat-irodori-caption-llm-model-wrap" style="display:none;">
                                                <span class="chat-field-label">モデル名（空=ペルソナモデル）</span>
                                                <input type="text" id="chat-irodori-caption-llm-model" class="chat-field-input"
                                                    placeholder="ペルソナモデルを使用" />
                                            </div>
                                        </div>
                                    </details>
                                    <!-- Test playback -->
                                    <div class="chat-test-row">
                                        <button type="button" class="chat-test-btn" data-action="chat-test-tts" aria-label="音声をテスト再生"><i data-lucide="play"></i> テスト再生</button>
                                        <span id="chat-voice-test-status" class="chat-test-status"></span>
                                    </div>
                                </div>
                            </div>
                        </details>"""
