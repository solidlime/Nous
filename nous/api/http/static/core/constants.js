/* =================================================================
   CONSTANTS — Single source of truth for all colors, labels
   ================================================================= */
;(function(N) {

N.Core.CHART_COLORS = [
  "#a78bfa", "#f472b6", "#60a5fa", "#34d399", "#fbbf24",
  "#fb923c", "#f87171", "#2dd4bf", "#a3e635", "#e879f9",
];

N.Core.EMOTION_COLORS = {
  joy: "#fbbf24", sadness: "#60a5fa", anger: "#f87171",
  fear: "#a78bfa", surprise: "#fb923c", disgust: "#6ee7b7",
  love: "#ec4899", neutral: "#94a3b8", anticipation: "#F59E0B",
  trust: "#10B981", anxiety: "#8B5CF6", excitement: "#EC4899",
  frustration: "#DC2626", nostalgia: "#92400E", pride: "#F97316",
  shame: "#BE185D", guilt: "#78350F", loneliness: "#1E3A5F",
  contentment: "#065F46", curiosity: "#0891B2", awe: "#5B21B6",
  relief: "#34D399",   happiness: "#fbbf24", calm: "#2dd4bf",
};

N.Core.EMOTION_COLORS_PORTRAIT = {
  joy: "#fbbf24",
  sadness: "#60a5fa",
  anger: "#ef4444",
  fear: "#a78bfa",
  surprise: "#f472b6",
  disgust: "#84cc16",
  trust: "#34d399",
  anticipation: "#fb923c",
  neutral: "#94a3b8",
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
  nostalgia: "linear-gradient(90deg,#a78bfa,#c4b5fd)",
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
  arousal: "linear-gradient(90deg,#a78bfa,#c4b5fd)",
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

})(window.Nous);
