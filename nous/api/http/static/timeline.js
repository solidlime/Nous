
/* =================================================================
   MEMORY TIMELINE
   ================================================================= */
const TL_EMOTION_COLORS = {
    joy:         { bg: 'rgba(251,191,36,0.15)',  border: '#FBBF24', emoji: '<i data-lucide="smile"></i>' },
    sadness:     { bg: 'rgba(96,165,250,0.15)',  border: '#60A5FA', emoji: '<i data-lucide="frown"></i>' },
    anger:       { bg: 'rgba(248,113,113,0.15)', border: '#F87171', emoji: '<i data-lucide="angry"></i>' },
    love:        { bg: 'rgba(244,114,182,0.15)', border: '#F472B6', emoji: '<i data-lucide="heart"></i>' },
    fear:        { bg: 'rgba(167,139,250,0.15)', border: '#A78BFA', emoji: '<i data-lucide="skull"></i>' },
    surprise:    { bg: 'rgba(52,211,153,0.15)',  border: '#34D399', emoji: '<i data-lucide="sparkles"></i>' },
    neutral:     { bg: 'rgba(156,163,175,0.15)', border: '#9CA3AF', emoji: '<i data-lucide="meh"></i>' },
    excitement:  { bg: 'rgba(245,158,11,0.15)',  border: '#F59E0B', emoji: '<i data-lucide="star"></i>' },
    pride:       { bg: 'rgba(129,140,248,0.15)', border: '#818CF8', emoji: '<i data-lucide="feather"></i>' },
    shame:       { bg: 'rgba(251,113,133,0.15)', border: '#FB7185', emoji: '<i data-lucide="eye-off"></i>' },
    curiosity:   { bg: 'rgba(45,212,191,0.15)',  border: '#2DD4BF', emoji: '<i data-lucide="brain-circuit"></i>' },
    anxiety:     { bg: 'rgba(248,113,113,0.12)', border: '#F87171', emoji: '<i data-lucide="activity"></i>' },
    frustration: { bg: 'rgba(251,146,60,0.15)',  border: '#FB923C', emoji: '<i data-lucide="alert-triangle"></i>' },
    nostalgia:   { bg: 'rgba(167,139,250,0.12)', border: '#A78BFA', emoji: '<i data-lucide="sunrise"></i>' },
    trust:       { bg: 'rgba(52,211,153,0.12)',  border: '#34D399', emoji: '<i data-lucide="handshake"></i>' },
    loneliness:  { bg: 'rgba(148,163,184,0.15)', border: '#94A3B8', emoji: '<i data-lucide="frown"></i>' },
    contentment: { bg: 'rgba(134,239,172,0.15)', border: '#86EFAC', emoji: '<i data-lucide="smile-plus"></i>' },
    awe:         { bg: 'rgba(192,132,252,0.15)', border: '#C084FC', emoji: '<i data-lucide="sun"></i>' },
    relief:      { bg: 'rgba(110,231,183,0.15)', border: '#6EE7B7', emoji: '<i data-lucide="wind"></i>' },
    disgust:     { bg: 'rgba(163,230,53,0.15)',  border: '#A3E635', emoji: '<i data-lucide="thumbs-down"></i>' },
    guilt:       { bg: 'rgba(252,165,165,0.15)', border: '#FCA5A5', emoji: '<i data-lucide="heart-crack"></i>' },
};

function getEmotionStyle(emotion) {
    return TL_EMOTION_COLORS[emotion] || TL_EMOTION_COLORS['neutral'];
}

function buildEmotionLegend() {
    const legend = document.getElementById('tl-legend');
    if (!legend) return;
    let html = '';
    for (const [emo, style] of Object.entries(TL_EMOTION_COLORS)) {
        html += '<span><span class="tl-legend-dot" style="background:' + style.border + '"></span>' + style.emoji + ' ' + emo + '</span>';
    }
    legend.innerHTML = html;
    // Populate emotion filter dropdown
    const sel = document.getElementById('tl-emotion');
    if (sel) {
        sel.innerHTML = '<option value="">すべて</option>';
        for (const emo of Object.keys(TL_EMOTION_COLORS).sort()) {
            sel.innerHTML += '<option value="' + emo + '">' + TL_EMOTION_COLORS[emo].emoji + ' ' + emo + '</option>';
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
        var bodyLabels = {fatigue:'<i data-lucide="flame"></i> Fatigue',warmth:'<i data-lucide="flower"></i> Warmth',arousal:'<i data-lucide="zap"></i> Arousal',heart_rate:'<i data-lucide="heart-pulse"></i> Heart',pain:'<i data-lucide="activity"></i> Pain'};
        var bodyColors = {fatigue:'linear-gradient(90deg,#f87171,#fca5a5)',warmth:'linear-gradient(90deg,#f9a8d4,#fda4af)',arousal:'linear-gradient(90deg,#a78bfa,#c4b5fd)',heart_rate:'linear-gradient(90deg,#ef4444,#fca5a5)',pain:'linear-gradient(90deg,#f59e0b,#fcd34d)'};
        var hasBody = bodyKeys.some(function(k){ return mem.body_state[k] != null; });
        if (hasBody) {
            bodyHtml += '<div style="margin-bottom:10px;"><div class="tl-detail-label">Body State</div>';
            bodyKeys.forEach(function(k) {
                if (mem.body_state[k] != null) {
                    var val = mem.body_state[k];
                    var pct = Math.round(val * 100);
                    bodyHtml += '<div style="display:flex;align-items:center;gap:6px;margin-top:4px;">';
                    bodyHtml += '<span style="font-size:0.7rem;color:var(--text-muted);min-width:70px">' + bodyLabels[k] + '</span>';
                    bodyHtml += '<div style="flex:1;height:4px;background:rgba(255,255,255,0.1);border-radius:2px;overflow:hidden">';
                    bodyHtml += '<div style="height:100%;width:' + pct + '%;background:' + bodyColors[k] + ';border-radius:2px"></div>';
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
