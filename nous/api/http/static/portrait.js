const { esc, toast, api } = Nous.Core;

/* =================================================================
   TB07: PORTRAIT GENERATION UI
   ================================================================= */

/**
 * Portrait UI controller — handles SSE events for portrait generation,
 * loading states, and image display updates across Overview and Chat tabs.
 */

// ── Portrait SSE Event Handlers ──────────────────────────────────

/**
 * Handle portrait.generate_start SSE event.
 * Shows loading skeleton in both Overview and Chat portrait areas.
 */
function handlePortraitGenerateStart(data) {
  // Chat tab: show loading on portrait container
  const chatContainer = document.getElementById('portrait-container');
  if (chatContainer) {
    chatContainer.classList.add('portrait-loading');
    const img = document.getElementById('portrait-img');
    const placeholder = document.getElementById('portrait-placeholder');
    const status = document.getElementById('portrait-status');
    if (img) img.style.display = 'none';
    if (placeholder) {
      placeholder.style.display = 'flex';
      placeholder.innerHTML = '<div class="portrait-skeleton-pulse"></div>';
    }
    if (status) {
      status.textContent = 'Generating...';
      status.className = 'portrait-status generating';
    }
  }

  // Overview tab: show loading on overview portrait area
  const overviewPortrait = document.getElementById('overview-portrait-container');
  if (overviewPortrait) {
    overviewPortrait.classList.add('portrait-loading');
    const img = document.getElementById('overview-portrait-img');
    const placeholder = document.getElementById('overview-portrait-placeholder');
    const status = document.getElementById('overview-portrait-status');
    if (img) img.style.display = 'none';
    if (placeholder) {
      placeholder.style.display = 'flex';
      placeholder.innerHTML = '<div class="portrait-skeleton-pulse"></div>';
    }
    if (status) {
      status.textContent = 'Generating...';
      status.className = 'portrait-status generating';
    }
  }
}

/**
 * Handle portrait.generate_complete SSE event.
 * Updates portrait image in both Overview and Chat tabs.
 */
function handlePortraitGenerateComplete(data) {
  if (!data.image_base64) return;

  // Update Chat tab portrait
  if (typeof setPortraitImage === 'function') {
    setPortraitImage(data.image_base64, data.emotion);
  }

  // Update Overview tab portrait
  const overviewImg = document.getElementById('overview-portrait-img');
  const overviewPlaceholder = document.getElementById('overview-portrait-placeholder');
  const overviewStatus = document.getElementById('overview-portrait-status');
  const overviewContainer = document.getElementById('overview-portrait-container');

  if (overviewImg) {
    overviewImg.src = 'data:image/png;base64,' + data.image_base64;
    overviewImg.style.display = 'block';
    overviewImg.classList.remove('fade-in');
    void overviewImg.offsetWidth; // trigger reflow
    overviewImg.classList.add('fade-in');
  }
  if (overviewPlaceholder) {
    overviewPlaceholder.style.display = 'none';
  }
  if (overviewStatus) {
    overviewStatus.textContent = '';
    overviewStatus.className = 'portrait-status';
  }
  if (overviewContainer) {
    overviewContainer.classList.remove('portrait-loading');
    // Set emotion border color
    if (data.emotion && EMOTION_COLORS_PORTRAIT[data.emotion]) {
      overviewContainer.classList.add('has-emotion');
      overviewContainer.style.setProperty('--portrait-emotion-color', EMOTION_COLORS_PORTRAIT[data.emotion]);
    } else {
      overviewContainer.classList.remove('has-emotion');
      overviewContainer.style.removeProperty('--portrait-emotion-color');
    }
  }

  // Remove loading state from Chat container
  const chatContainer = document.getElementById('portrait-container');
  if (chatContainer) {
    chatContainer.classList.remove('portrait-loading');
  }

  toast('🎨 Portrait updated', 'info');
}

/**
 * Handle portrait.generate_error SSE event.
 * Shows error state and falls back to emotion emoji.
 */
function handlePortraitGenerateError(data) {
  const errorEmoji = data.fallback_emoji || '😐';
  const errorMsg = data.error || 'Generation failed';

  // Chat tab: show fallback
  const chatContainer = document.getElementById('portrait-container');
  if (chatContainer) {
    chatContainer.classList.remove('portrait-loading');
    const img = document.getElementById('portrait-img');
    const placeholder = document.getElementById('portrait-placeholder');
    const status = document.getElementById('portrait-status');
    if (img) img.style.display = 'none';
    if (placeholder) {
      placeholder.style.display = 'flex';
      placeholder.textContent = errorEmoji;
      placeholder.style.fontSize = '2.5rem';
    }
    if (status) {
      status.textContent = errorMsg;
      status.className = 'portrait-status error';
    }
  }

  // Overview tab: show fallback
  const overviewContainer = document.getElementById('overview-portrait-container');
  if (overviewContainer) {
    overviewContainer.classList.remove('portrait-loading');
    const img = document.getElementById('overview-portrait-img');
    const placeholder = document.getElementById('overview-portrait-placeholder');
    const status = document.getElementById('overview-portrait-status');
    if (img) img.style.display = 'none';
    if (placeholder) {
      placeholder.style.display = 'flex';
      placeholder.textContent = errorEmoji;
      placeholder.style.fontSize = '2.5rem';
    }
    if (status) {
      status.textContent = errorMsg;
      status.className = 'portrait-status error';
    }
  }

  toast('⚠️ Portrait generation failed: ' + errorMsg, 'warning');
}

// ── Reference Image Helpers ──────────────────────────────────────

/**
 * Read a File as a data URL for preview thumbnail display.
 * @param {File} file
 * @returns {Promise<string>}
 */
function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });
}

/**
 * Handle reference image file selection — update preview thumbnail.
 */
function onReferenceImageSelected(input) {
  const preview = document.getElementById('overview-portrait-ref-preview');
  const removeBtn = document.getElementById('overview-portrait-ref-remove');
  const file = input.files ? input.files[0] : null;
  if (file) {
    readFileAsDataURL(file).then((dataUrl) => {
      if (preview) {
        preview.src = dataUrl;
        preview.style.display = 'block';
      }
      if (removeBtn) removeBtn.style.display = 'inline-flex';
    });
  } else {
    if (preview) { preview.src = ''; preview.style.display = 'none'; }
    if (removeBtn) removeBtn.style.display = 'none';
  }
}

/**
 * Clear the reference image selection.
 */
function clearReferenceImage() {
  const input = document.getElementById('overview-portrait-ref-input');
  const preview = document.getElementById('overview-portrait-ref-preview');
  const removeBtn = document.getElementById('overview-portrait-ref-remove');
  if (input) input.value = '';
  if (preview) { preview.src = ''; preview.style.display = 'none'; }
  if (removeBtn) removeBtn.style.display = 'none';
}

// ── Generate Now (Overview Tab) ──────────────────────────────────

/**
 * Trigger portrait generation from Overview tab.
 * Reads scene text from input field, optional reference image, and sends POST request.
 */
async function generatePortraitNow() {
  if (!S.persona) {
    toast('Please select a persona first', 'error');
    return;
  }

  const sceneInput = document.getElementById('overview-portrait-scene');
  const scene = sceneInput ? sceneInput.value.trim() : '';
  const btn = document.getElementById('overview-portrait-generate-btn');
  const refInput = document.getElementById('overview-portrait-ref-input');
  const refFile = refInput && refInput.files ? refInput.files[0] : null;

  // Disable button during generation
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader"></i> Generating...';
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  try {
    let result;

    if (refFile) {
      // ── Multipart upload with reference image ────────────────
      const formData = new FormData();
      if (scene) formData.append('scene', scene);
      formData.append('reference_image', refFile);

      const resp = await fetch('/api/portrait/' + encodeURIComponent(S.persona), {
        method: 'POST',
        body: formData,
      });
      result = await resp.json();
    } else {
      // ── Plain JSON (no reference image) ──────────────────────
      const body = {};
      if (scene) body.scene = scene;

      result = await api('/api/portrait/' + encodeURIComponent(S.persona), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    }

    if (result.image_base64) {
      // Update Overview portrait
      const overviewImg = document.getElementById('overview-portrait-img');
      const overviewPlaceholder = document.getElementById('overview-portrait-placeholder');
      const overviewStatus = document.getElementById('overview-portrait-status');
      const overviewContainer = document.getElementById('overview-portrait-container');

      if (overviewImg) {
        overviewImg.src = 'data:image/png;base64,' + result.image_base64;
        overviewImg.style.display = 'block';
        overviewImg.classList.remove('fade-in');
        void overviewImg.offsetWidth;
        overviewImg.classList.add('fade-in');
      }
      if (overviewPlaceholder) overviewPlaceholder.style.display = 'none';
      if (overviewStatus) {
        overviewStatus.textContent = '';
        overviewStatus.className = 'portrait-status';
      }
      if (overviewContainer) {
        overviewContainer.classList.remove('portrait-loading');
        if (result.emotion && EMOTION_COLORS_PORTRAIT[result.emotion]) {
          overviewContainer.classList.add('has-emotion');
          overviewContainer.style.setProperty('--portrait-emotion-color', EMOTION_COLORS_PORTRAIT[result.emotion]);
        }
      }

      // Also update Chat tab portrait
      if (typeof setPortraitImage === 'function') {
        setPortraitImage(result.image_base64, result.emotion);
      }

      toast('🎨 Portrait generated!', 'success');
    } else if (result.fallback_emoji) {
      // Show fallback emoji
      const overviewPlaceholder = document.getElementById('overview-portrait-placeholder');
      if (overviewPlaceholder) {
        overviewPlaceholder.style.display = 'flex';
        overviewPlaceholder.textContent = result.fallback_emoji;
        overviewPlaceholder.style.fontSize = '2.5rem';
      }
      toast('Using fallback emoji: ' + result.fallback_emoji, 'info');
    }
  } catch (e) {
    console.error('[generatePortraitNow] failed:', e);
    toast('Portrait generation failed: ' + e.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<i data-lucide="image"></i> Generate Now';
      if (typeof lucide !== 'undefined') lucide.createIcons();
    }
  }
}

// ── Overview Tab Portrait Section Renderer ───────────────────────

/**
 * Render the portrait section HTML for the Overview tab.
 * Called from loadOverview() to inject portrait display area.
 *
 * @param {Object} data - Dashboard data (may contain latest portrait info)
 * @returns {string} HTML string for portrait section
 */
function renderOverviewPortraitSection(data) {
  const ctx = data.context || {};
  const emotion = ctx.emotion || 'neutral';
  const emotionColor = EMOTION_COLORS_PORTRAIT[emotion] || '#94a3b8';

  return `
    <div class="glass glass-hoverable p-6 mb-6">
      <div class="card-title"><i data-lucide="image" aria-hidden="true"></i> Portrait</div>
      <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap;">
        <!-- Portrait image area -->
        <div id="overview-portrait-container" class="portrait-container" style="flex-shrink:0; width:160px; height:160px; position:relative;">
          <div id="overview-portrait-placeholder" style="display:flex; align-items:center; justify-content:center; width:100%; height:100%; border-radius:var(--card-radius); background:var(--glass-bg); border:1px solid var(--glass-border);">
            <span style="font-size:3rem;">${esc(EMOTION_EMOJI_MAP[emotion] || '😐')}</span>
          </div>
          <img id="overview-portrait-img" alt="Persona portrait" style="display:none; width:100%; height:100%; object-fit:cover; border-radius:var(--card-radius); border:2px solid ${emotionColor}; transition:border-color 0.3s ease;" />
          <div id="overview-portrait-status" class="portrait-status"></div>
        </div>
        <!-- Generate controls -->
        <div style="flex:1; min-width:200px;">
          <div style="margin-bottom:10px;">
            <label for="overview-portrait-scene" style="font-size:0.82rem; color:var(--text-muted); display:block; margin-bottom:4px;">Scene description (optional)</label>
            <input type="text" id="overview-portrait-scene" class="glass-input" placeholder="e.g. Standing in a moonlit garden…" style="width:100%; font-size:0.85rem;" />
          </div>
          <div style="margin-bottom:10px;">
            <label for="overview-portrait-ref-input" style="font-size:0.82rem; color:var(--text-muted); display:block; margin-bottom:4px;">Reference image (optional — for img2img)</label>
            <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
              <input type="file" id="overview-portrait-ref-input" accept="image/*" onchange="onReferenceImageSelected(this)" style="font-size:0.78rem; flex:1; min-width:120px;" class="glass-input" />
              <img id="overview-portrait-ref-preview" alt="Reference preview" style="display:none; width:36px; height:36px; object-fit:cover; border-radius:6px; border:1px solid var(--glass-border);" />
              <button id="overview-portrait-ref-remove" type="button" onclick="clearReferenceImage()" style="display:none; background:none; border:none; color:var(--accent-red); cursor:pointer; font-size:0.8rem; padding:4px;" aria-label="Clear reference image">&times;</button>
            </div>
          </div>
          <button id="overview-portrait-generate-btn" class="glass-btn" onclick="generatePortraitNow()" aria-label="Generate portrait now" style="width:100%;">
            <i data-lucide="image" aria-hidden="true"></i> Generate Now
          </button>
          <div style="margin-top:8px; font-size:0.72rem; color:var(--text-muted);">
            Emotion: <span style="color:${emotionColor}; font-weight:600;">${esc(emotion)}</span>
          </div>
        </div>
      </div>
    </div>`;
}

// ── Helper: Emotion Emoji Map (fallback) ─────────────────────────

const EMOTION_EMOJI_MAP = {
  joy: '😊',
  sadness: '😢',
  anger: '😠',
  fear: '😨',
  surprise: '😲',
  disgust: '🤢',
  love: '😍',
  neutral: '😐',
  anticipation: '🤔',
  trust: '🤝',
  anxiety: '😰',
  excitement: '🤩',
  frustration: '😤',
  nostalgia: '🥹',
  pride: '😌',
  shame: '😳',
  guilt: '😣',
  loneliness: '🥺',
  contentment: '☺️',
  curiosity: '🧐',
  awe: '🤯',
  relief: '😮‍💨',
  happiness: '😄',
  calm: '😌',
};


