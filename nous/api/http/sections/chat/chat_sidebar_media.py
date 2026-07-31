"""Media settings — image generation (ComfyUI), voice/TTS (Irodori), and background/standing picture."""


def _render_background_section() -> str:
    """Background image and standing picture settings."""
    return """
                        <!-- 背景画像・立ち絵 -->
                        <details data-category="background" id="chat-background-section">
                            <summary><i data-lucide="image"></i> 背景・立ち絵 <span class="chat-help-icon" data-category="background" tabindex="0" role="button" aria-label="ヘルプ"><i data-lucide="help-circle"></i></span></summary>
                            <div class="details-body">
                                <div>
                                    <div class="chat-field-label">背景画像URL <span style="color:var(--text-muted);font-size:0.7rem;">（ライトモード用）</span></div>
                                    <input type="url" id="chat-bg-url" class="chat-field-input" placeholder="https://example.com/bg-light.jpg" aria-label="背景画像URL" />
                                </div>
                                <div>
                                    <div class="chat-field-label">背景画像URL <span style="color:var(--text-muted);font-size:0.7rem;">（ダークモード用・未設定ならライト用を共通利用）</span></div>
                                    <input type="url" id="chat-bg-dark-url" class="chat-field-input" placeholder="https://example.com/bg-dark.jpg" aria-label="ダークモード背景画像URL" />
                                </div>
                                <div>
                                    <div class="chat-field-label">立ち絵URL</div>
                                    <input type="url" id="chat-standing-pic-url" class="chat-field-input" placeholder="https://example.com/standing.png" aria-label="立ち絵URL" />
                                </div>
                                <p style="font-size:0.72rem;color:var(--text-muted);margin:0;">背景は薄くオーバーレイ表示されます。設定を反映するには保存後、ページを再読み込みしてください。</p>
                            </div>
                        </details>"""


def _render_image_section() -> str:
    """Image generation settings — ComfyUI, checkpoint, LoRA, resolution."""
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
                                        <div class="chat-field-label" style="font-size:0.78rem;">プリセット解像度 <span style="font-weight:300;color:var(--text-dim);">(LLMが選ぶ解像度プリセット)</span></div>
                                        <div style="display:grid;grid-template-columns:auto 1fr 1fr 1fr;gap:4px 6px;align-items:center;font-size:0.75rem;margin-top:4px;">
                                            <span></span>
                                            <span style="text-align:center;color:var(--text-dim);">Large</span>
                                            <span style="text-align:center;color:var(--text-dim);">Medium</span>
                                            <span style="text-align:center;color:var(--text-dim);">Small</span>
                                            <span style="color:var(--text-dim);">縦長</span>
                                            <input type="text" id="chat-image-gen-preset-portrait_large" class="chat-field-input" value="832x1216" style="width:100%;font-size:0.72rem;text-align:center;" />
                                            <input type="text" id="chat-image-gen-preset-portrait_medium" class="chat-field-input" value="768x1024" style="width:100%;font-size:0.72rem;text-align:center;" />
                                            <input type="text" id="chat-image-gen-preset-portrait_small" class="chat-field-input" value="576x768" style="width:100%;font-size:0.72rem;text-align:center;" />
                                            <span style="color:var(--text-dim);">横長</span>
                                            <input type="text" id="chat-image-gen-preset-landscape_large" class="chat-field-input" value="1216x832" style="width:100%;font-size:0.72rem;text-align:center;" />
                                            <input type="text" id="chat-image-gen-preset-landscape_medium" class="chat-field-input" value="1024x768" style="width:100%;font-size:0.72rem;text-align:center;" />
                                            <input type="text" id="chat-image-gen-preset-landscape_small" class="chat-field-input" value="768x576" style="width:100%;font-size:0.72rem;text-align:center;" />
                                            <span style="color:var(--text-dim);">正方形</span>
                                            <input type="text" id="chat-image-gen-preset-square_large" class="chat-field-input" value="1024x1024" style="width:100%;font-size:0.72rem;text-align:center;" />
                                            <input type="text" id="chat-image-gen-preset-square_medium" class="chat-field-input" value="768x768" style="width:100%;font-size:0.72rem;text-align:center;" />
                                            <input type="text" id="chat-image-gen-preset-square_small" class="chat-field-input" value="512x512" style="width:100%;font-size:0.72rem;text-align:center;" />
                                        </div>
                                        <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
                                            <span class="chat-field-label" style="font-size:0.78rem;">デフォルト</span>
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
                                                    <option value="heun">Heun</option>
                                                    <option value="heunpp2">Heun++ 2</option>
                                                    <option value="dpm_2">DPM 2</option>
                                                    <option value="dpm_2_ancestral">DPM 2 Ancestral</option>
                                                    <option value="lms">LMS</option>
                                                    <option value="dpm_fast">DPM Fast</option>
                                                    <option value="dpm_adaptive">DPM Adaptive</option>
                                                    <option value="dpmpp_2s_ancestral">DPM++ 2S Ancestral</option>
                                                    <option value="dpmpp_sde">DPM++ SDE</option>
                                                    <option value="dpmpp_sde_gpu">DPM++ SDE (GPU)</option>
                                                    <option value="dpmpp_2m">DPM++ 2M</option>
                                                    <option value="dpmpp_2m_sde">DPM++ 2M SDE</option>
                                                    <option value="dpmpp_2m_sde_gpu">DPM++ 2M SDE (GPU)</option>
                                                    <option value="dpmpp_3m_sde">DPM++ 3M SDE</option>
                                                    <option value="dpmpp_3m_sde_gpu">DPM++ 3M SDE (GPU)</option>
                                                    <option value="ddpm">DDPM</option>
                                                    <option value="lcm">LCM</option>
                                                    <option value="uni_pc">UniPC</option>
                                                    <option value="uni_pc_bh2">UniPC (BH2)</option>
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
                                                    <option value="beta">Beta</option>
                                                    <option value="linear_quadratic">Linear Quadratic</option>
                                                    <option value="kl_optimal">KL Optimal</option>
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
                                        </div>
                                    </details>
                                    <!-- workflow template path -->
                                    <div style="margin-top:8px;">
                                        <div class="chat-field-label" style="font-size:0.78rem;">ワークフローテンプレート（必須）</div>
                                        <input type="text" id="chat-image-gen-template" class="chat-field-input"
                                            placeholder="例: /data/workflows/pony_ipadapter.json"
                                            style="width:100%;font-size:0.78rem;" />
                                    </div>
                                    <!-- Reference image upload (i2i fixed — always shown) -->
                                    <div id="chat-image-gen-ref-upload" style="margin-top:8px;">
                                        <div class="chat-field-label" style="font-size:0.82rem;margin-bottom:4px;">参照画像</div>
                                        <input type="file" id="chat-image-gen-ref-file" accept="image/*"
                                            style="font-size:0.78rem;width:100%;margin-bottom:4px;" />
                                        <button id="chat-image-gen-ref-upload-btn" class="chat-clear-btn" style="font-size:0.78rem;padding:4px 10px;"
                                            onclick="N.ImageGen.uploadReferenceImage()">
                                            <i data-lucide="upload"></i> アップロード
                                        </button>
                                        <span id="chat-image-gen-ref-status" style="font-size:0.72rem;color:var(--text-muted);margin-left:8px;"></span>
                                        <img id="chat-image-gen-ref-thumb" src="" alt="参照画像プレビュー"
                                            style="display:none;max-width:120px;max-height:120px;margin-top:6px;border-radius:6px;border:1px solid var(--border-color);object-fit:contain;" />
                                    </div>
                                    <div style="display:flex;gap:8px;align-items:center;">
                                        <button class="chat-clear-btn" style="font-size:0.78rem;padding:6px 12px;" onclick="N.Chat.settings.testImageGen()"><i data-lucide="play"></i> テスト生成</button>
                                        <span id="chat-image-test-status" style="font-size:0.72rem;color:var(--text-muted);min-height:16px;"></span>
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
                                            <!-- LLM caption generation -->
                                            <div style="margin-top:8px;">
                                                <div style="display:flex;align-items:center;gap:6px;">
                                                    <input type="checkbox" id="chat-irodori-caption-llm" class="chat-field-input"
                                                        style="width:auto;accent-color:var(--accent-purple);"
                                                        onchange="document.getElementById('chat-irodori-caption-llm-model-wrap').style.display=this.checked?'block':'none'" />
                                                    <span class="chat-field-label" style="font-size:0.78rem;">LLMキャプション生成</span>
                                                </div>
                                                <div id="chat-irodori-caption-llm-model-wrap" style="display:none;margin-top:6px;">
                                                    <span class="chat-field-label" style="font-size:0.72rem;color:var(--text-muted);">モデル名（空=ペルソナモデル）</span>
                                                    <input type="text" id="chat-irodori-caption-llm-model" class="chat-field-input"
                                                        placeholder="ペルソナモデルを使用"
                                                        style="width:100%;font-size:0.78rem;" />
                                                </div>
                                            </div>
                                        </div>
                                    </details>
                                    <!-- Test playback -->
                                    <div style="display:flex;gap:8px;align-items:center;margin-top:4px;">
                                        <button class="chat-clear-btn" style="font-size:0.78rem;padding:6px 12px;" onclick="N.Chat.tts.test()" aria-label="音声をテスト再生"><i data-lucide="play"></i> テスト再生</button>
                                        <span id="chat-voice-test-status" style="font-size:0.72rem;color:var(--text-muted);min-height:16px;"></span>
                                    </div>
                                </div>
                            </div>
                        </details>"""
