
/* =================================================================
   MEMORY TIMELINE
   ================================================================= */
/* Timeline emoji icons — border/bg derived from EMOTION_COLORS global */
const TL_EMOJI = {
    joy: '<i data-lucide="smile"></i>',   sadness: '<i data-lucide="frown"></i>',
    anger: '<i data-lucide="angry"></i>',  love: '<i data-lucide="heart"></i>',
    fear: '<i data-lucide="skull"></i>',  surprise: '<i data-lucide="sparkles"></i>',
    neutral: '<i data-lucide="meh"></i>', excitement: '<i data-lucide="star"></i>',
    pride: '<i data-lucide="feather"></i>', shame: '<i data-lucide="eye-off"></i>',
    curiosity: '<i data-lucide="brain-circuit"></i>', anxiety: '<i data-lucide="activity"></i>',
    frustration: '<i data-lucide="alert-triangle"></i>', nostalgia: '<i data-lucide="sunrise"></i>',
    trust: '<i data-lucide="handshake"></i>', loneliness: '<i data-lucide="frown"></i>',
    contentment: '<i data-lucide="smile-plus"></i>', awe: '<i data-lucide="sun"></i>',
    relief: '<i data-lucide="wind"></i>', disgust: '<i data-lucide="thumbs-down"></i>',
    guilt: '<i data-lucide="heart-crack"></i>',
};

function getEmotionStyle(emotion) {
    var c = EMOTION_COLORS[emotion] || '#94a3b8';
    var r = parseInt(c.slice(1,3), 16);
    var g = parseInt(c.slice(3,5), 16);
    var b = parseInt(c.slice(5,7), 16);
    return {
        bg: 'rgba(' + r + ',' + g + ',' + b + ',0.15)',
        border: c,
        emoji: TL_EMOJI[emotion] || '<i data-lucide="meh"></i>',
    };
}

function buildEmotionLegend() {
    const legend = document.getElementById('tl-legend');
    if (!legend) return;
    var emos = Object.keys(EMOTION_COLORS).sort();
    let html = '';
    for (var i = 0; i < emos.length; i++) {
        var style = getEmotionStyle(emos[i]);
        html += '<span><span class="tl-legend-dot" style="background:' + style.border + '"></span>' + style.emoji + ' ' + emos[i] + '</span>';
    }
    legend.innerHTML = html;
    // Populate emotion filter dropdown
    const sel = document.getElementById('tl-emotion');
    if (sel) {
        sel.innerHTML = '<option value="">すべて</option>';
        for (var j = 0; j < emos.length; j++) {
            var s = getEmotionStyle(emos[j]);
            sel.innerHTML += '<option value="' + emos[j] + '">' + s.emoji + ' ' + emos[j] + '</option>';
        }
    }
    setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 50);
}

let _timeline = null;
let _timelineItems = null;
let _timelineData = null;

async function loadTimeline() {
    if (!S.persona) return;
    const container = document.getElementById('tl-container');
    const loading = document.getElementById('tl-loading');
    if (!container) return;
    const perPage = parseInt(document.getElementById('tl-per-page')?.value || '100');
    const emotion = document.getElementById('tl-emotion')?.value || '';
    const tag = document.getElementById('tl-tag')?.value.trim() || '';
    const minImp = parseFloat(document.getElementById('tl-min-importance')?.value || '0');

    if (loading) loading.style.display = 'flex';

    try {
        let allMemories = [];
        let page = 1;
        let totalPages = 1;
        while (page <= totalPages && page <= 5) {  // max 5 pages
            const resp = await api('/api/observations/' + encodeURIComponent(S.persona) +
                '?page=' + page + '&per_page=' + perPage);
            if (!resp.memories) break;
            allMemories = allMemories.concat(resp.memories);
            totalPages = resp.total_pages || 1;
            page++;
        }

        // Filter client-side
        if (emotion) allMemories = allMemories.filter(m => m.emotion === emotion);
        if (tag) allMemories = allMemories.filter(m => (m.tags || []).some(t => t.toLowerCase().includes(tag.toLowerCase())));
        if (minImp > 0) allMemories = allMemories.filter(m => (m.importance || 0) >= minImp);

        _timelineData = allMemories;

        if (loading) loading.style.display = 'none';

        if (_timeline) { _timeline.destroy(); _timeline = null; }

        if (allMemories.length === 0) {
            container.innerHTML = '<div class="empty-state">' +
                '<div class="empty-state-icon"><i data-lucide="clock"></i></div>' +
                '<div class="empty-state-text">まだタイムラインがありません。<br>記憶を作成するとここに表示されます。</div>' +
                '<button class="empty-state-cta" onclick="switchTab(\'chat\')"><i data-lucide="message-circle"></i> Chatを開く</button>' +
                '</div>';
            setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 50);
            return;
        }

        const items = allMemories.map((m, i) => {
            const style = getEmotionStyle(m.emotion || 'neutral');
            const content = (m.content || '').substring(0, 100);
            const imp = m.importance != null ? m.importance : 0.5;
            return {
                id: m.key || i,
                content: style.emoji + ' ' + content,
                start: m.created_at ? new Date(m.created_at) : new Date(),
                title: '<div style="max-width:300px;white-space:normal;font-size:0.78rem;line-height:1.4;">' +
                       esc(m.content || '') + '</div>' +
                       '<div style="font-size:0.68rem;color:var(--text-muted);margin-top:4px;">' +
                       (style.emoji + ' ' + (m.emotion || 'neutral') + ' · imp:' + imp.toFixed(2)) + '</div>',
                style: 'background:' + style.bg + ';border-color:' + style.border + ';' +
                       'font-size:' + (0.65 + imp * 0.2) + 'rem;',
            };
        });

        _timelineItems = new vis.DataSet(items);

        const options = {
            height: '100%',
            minHeight: '500px',
            start: items.length > 0 ? new Date(items[items.length-1].start.getTime() - 86400000 * 7) : new Date(),
            end: new Date(),
            zoomable: true,
            moveable: true,
            selectable: true,
            multiselect: false,
            tooltip: { followMouse: true, overflowMethod: 'cap' },
            margin: { item: { vertical: 8 } },
            timeAxis: { scale: 'day', step: 1 },
            orientation: { axis: 'top' },
        };

        _timeline = new vis.Timeline(container, _timelineItems, options);
        setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 150);

        _timeline.on('select', function(props) {
            if (props.items.length > 0) {
                const id = props.items[0];
                const mem = _timelineData.find(m => (m.key || '') === id);
                if (mem) showTimelineDetail(mem);
            }
        });

        _timeline.on('doubleClick', function(props) {
            if (props.what === 'background') {
                _timeline.fit();
            }
        });

    } catch (e) {
        if (loading) { loading.textContent = '読み込み失敗: ' + e.message; loading.style.display = 'flex'; }
    }
}

function showTimelineDetail(mem) {
    const panel = document.getElementById('tl-detail-panel');
    if (!panel) return;
    document.getElementById('tl-detail-content').textContent = mem.content || '';
    const style = getEmotionStyle(mem.emotion || 'neutral');
    document.getElementById('tl-detail-emotion').innerHTML = style.emoji + ' ' + esc(mem.emotion || 'neutral');
    document.getElementById('tl-detail-importance').textContent = (mem.importance != null ? mem.importance.toFixed(2) : '0.50');
    document.getElementById('tl-detail-time').textContent = mem.created_at
        ? new Date(mem.created_at).toLocaleString('ja-JP') : '—';
    document.getElementById('tl-detail-tags').textContent = (mem.tags || []).join(', ') || '—';

    /* Body State & Emotions bars */
    var bodyHtml = '';
    if (mem.body_state) {
        var bodyKeys = ['fatigue','warmth','arousal','heart_rate','pain'];
        /* Constants now from core/constants.js via adapter globals */
        var hasBody = bodyKeys.some(function(k){ return mem.body_state[k] != null; });
        if (hasBody) {
            bodyHtml += '<div style="margin-bottom:10px;"><div class="tl-detail-label">Body State</div>';
            bodyKeys.forEach(function(k) {
                if (mem.body_state[k] != null) {
                    var val = mem.body_state[k];
                    var pct = Math.round(val * 100);
                    bodyHtml += '<div style="display:flex;align-items:center;gap:6px;margin-top:4px;">';
                    bodyHtml += '<span style="font-size:0.7rem;color:var(--text-muted);min-width:70px">' + BODY_LABELS[k] + '</span>';
                    bodyHtml += '<div style="flex:1;height:4px;background:rgba(255,255,255,0.1);border-radius:2px;overflow:hidden">';
                    bodyHtml += '<div style="height:100%;width:' + pct + '%;background:' + BODY_BAR_COLORS[k] + ';border-radius:2px"></div>';
                    bodyHtml += '</div>';
                    bodyHtml += '<span style="font-size:0.7rem;color:var(--text-muted);min-width:28px;text-align:right">' + pct + '%</span>';
                    bodyHtml += '</div>';
                }
            });
            bodyHtml += '</div>';
        }
    }
    if (mem.emotion) {
        bodyHtml += '<div style="margin-bottom:16px">' + renderEmotionBars(mem.emotion, mem.emotion_intensity) + '</div>';
    }
    document.getElementById('tl-detail-body').innerHTML = bodyHtml;

    panel.classList.add('open');
    setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 50);
}

function closeTimelineDetail() {
    document.getElementById('tl-detail-panel')?.classList.remove('open');
}

// Initialize — watch tab activation via DOM class changes (replaces switchTab monkey-patch)
document.addEventListener('DOMContentLoaded', () => {
    buildEmotionLegend();
    const container = document.querySelector('main.main-content');
    if (container) {
        const obs = new MutationObserver((mutations) => {
            for (const m of mutations) {
                if (m.type === 'attributes' && m.attributeName === 'class') {
                    const el = m.target;
                    if (el.classList?.contains('tab-panel') && el.classList.contains('active')) {
                        const tabId = el.id.replace('tab-', '');
                        window.dispatchEvent(new CustomEvent('tab:changed', { detail: { tabId } }));
                        if (tabId === 'timeline') {
                            setTimeout(loadTimeline, 200);
                        }
                    }
                }
            }
        });
        obs.observe(container, { attributes: true, attributeFilter: ['class'], subtree: true });
    }
    // Load if timeline already active
    if (document.getElementById('tab-timeline')?.classList.contains('active')) {
        setTimeout(loadTimeline, 200);
    }
});
