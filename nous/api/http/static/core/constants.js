/* =================================================================
   CONSTANTS — Single source of truth for all colors, labels
   ================================================================= */
;(function(N) {

N.Core.CHART_COLORS = [
  "#007aff", "#f472b6", "#60a5fa", "#34d399", "#fbbf24",
  "#fb923c", "#f87171", "#2dd4bf", "#a3e635", "#e879f9",
];

N.Core.EMOTION_COLORS = {
  joy: "#fbbf24", sadness: "#60a5fa", anger: "#f87171",
  fear: "#5856d6", surprise: "#fb923c", disgust: "#6ee7b7",
  love: "#ec4899", neutral: "#94a3b8", anticipation: "#F59E0B",
  trust: "#10B981", anxiety: "#8B5CF6", excitement: "#EC4899",
  frustration: "#DC2626", nostalgia: "#92400E", pride: "#F97316",
  shame: "#BE185D", guilt: "#78350F", loneliness: "#1E3A5F",
  contentment: "#065F46", curiosity: "#0891B2", awe: "#5B21B6",
  relief: "#34D399",   happiness: "#fbbf24", calm: "#2dd4bf",
};


N.Core.EMOTION_BAR_COLORS = {
  joy: "linear-gradient(90deg,#fbbf24,#fcd34d)",
  sadness: "linear-gradient(90deg,#60a5fa,#93c5fd)",
  anger: "linear-gradient(90deg,#ef4444,#fca5a5)",
  fear: "linear-gradient(90deg,#a855f7,#c4b5fd)",
  disgust: "linear-gradient(90deg,#22c55e,#86efac)",
  surprise: "linear-gradient(90deg,#ec4899,#f9a8d4)",
  love: "linear-gradient(90deg,#fb7185,#fda4af)",
  trust: "linear-gradient(90deg,#14b8a6,#5eead4)",
  anticipation: "linear-gradient(90deg,#f97316,#fdba74)",
  curiosity: "linear-gradient(90deg,#6366f1,#a5b4fc)",
  neutral: "linear-gradient(90deg,#9ca3af,#d1d5db)",
  excitement: "linear-gradient(90deg,#f59e0b,#fbbf24)",
  pride: "linear-gradient(90deg,#818cf8,#a5b4fc)",
  shame: "linear-gradient(90deg,#fb7185,#fda4af)",
  nostalgia: "linear-gradient(90deg,#5856d6,#a5b4fc)",
  anxiety: "linear-gradient(90deg,#f87171,#fca5a5)",
  contentment: "linear-gradient(90deg,#86efac,#bbf7d0)",
  frustration: "linear-gradient(90deg,#fb923c,#fdba74)",
  loneliness: "linear-gradient(90deg,#94a3b8,#cbd5e1)",
  awe: "linear-gradient(90deg,#c084fc,#e9d5ff)",
  relief: "linear-gradient(90deg,#6ee7b7,#a7f3d0)",
};

N.Core.BODY_BAR_COLORS = {
  fatigue: "linear-gradient(90deg,#f87171,#fca5a5)",
  warmth: "linear-gradient(90deg,#f9a8d4,#fda4af)",
  arousal: "linear-gradient(90deg,#5856d6,#a5b4fc)",
  heart_rate: "linear-gradient(90deg,#ef4444,#fca5a5)",
  pain: "linear-gradient(90deg,#f59e0b,#fcd34d)",
};

N.Core.BODY_LABELS = {
  fatigue: '<i data-lucide="flame"></i> Fatigue',
  warmth: '<i data-lucide="flower"></i> Warmth',
  arousal: '<i data-lucide="zap"></i> Arousal',
  heart_rate: '<i data-lucide="heart-pulse"></i> Heart',
  pain: '<i data-lucide="activity"></i> Pain',
};

/* Timeline emoji icons — used by timeline.js for emotion display */
N.Core.EMOTION_ICONS = {
  joy: '<i data-lucide="smile"></i>',       sadness: '<i data-lucide="frown"></i>',
  anger: '<i data-lucide="angry"></i>',      love: '<i data-lucide="heart"></i>',
  fear: '<i data-lucide="skull"></i>',       surprise: '<i data-lucide="sparkles"></i>',
  neutral: '<i data-lucide="meh"></i>',      excitement: '<i data-lucide="star"></i>',
  pride: '<i data-lucide="feather"></i>',    shame: '<i data-lucide="eye-off"></i>',
  curiosity: '<i data-lucide="brain-circuit"></i>', anxiety: '<i data-lucide="activity"></i>',
  frustration: '<i data-lucide="alert-triangle"></i>', nostalgia: '<i data-lucide="sunrise"></i>',
  trust: '<i data-lucide="handshake"></i>',  loneliness: '<i data-lucide="frown"></i>',
  contentment: '<i data-lucide="smile-plus"></i>',  awe: '<i data-lucide="sun"></i>',
  relief: '<i data-lucide="wind"></i>',      disgust: '<i data-lucide="thumbs-down"></i>',
  guilt: '<i data-lucide="heart-crack"></i>',
  anticipation: '<i data-lucide="clock"></i>', happiness: '<i data-lucide="smile"></i>',
  calm: '<i data-lucide="moon"></i>',
};

})(window.Nous);
