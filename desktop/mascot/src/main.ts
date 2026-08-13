import { fetch } from "@tauri-apps/plugin-http";

// ── Config ────────────────────────────────────────────────────────
// NOUS_URL env var overrides the default server (vite envPrefix includes NOUS_).
declare const NOUS_URL: string | undefined;
const SERVER: string = NOUS_URL || "http://192.168.50.150:26262";
const PERSONA = "herta";
const CHAT_URL = `${SERVER}/api/chat/${PERSONA}`;
const TTS_URL = `${SERVER}/api/tts/${PERSONA}`;

declare global {
  interface Window {
    Nous: {
      Avatar: {
        init: (el: HTMLElement | null, opts: object) => AvatarApi;
      };
    };
  }
}

interface AvatarApi {
  setEmotion(emotion: string, intensity?: number): void;
  startTalking(): void;
  stopTalking(): void;
  setMouth(openRatio: number): void;
}

// ── DOM refs ──────────────────────────────────────────────────────
const avatarEl = document.getElementById("avatar") as HTMLElement;
const bubbleText = document.getElementById("bubble-text") as HTMLElement;
const input = document.getElementById("chat-input") as HTMLInputElement;
const sendBtn = document.getElementById("chat-send") as HTMLButtonElement;

let avatar: AvatarApi;
let fullText = "";
let streaming = false;
let audio: HTMLAudioElement | null = null;
let voiceMeter: {
  ctx: AudioContext;
  source: MediaElementAudioSourceNode;
  analyser: AnalyserNode;
  buf: Uint8Array;
  timer: number;
} | null = null;

// ── Avatar init ───────────────────────────────────────────────────
avatar = window.Nous.Avatar.init(avatarEl, {
  baseUrl: SERVER,
  persona: PERSONA,
  enabled: true,
  mouthMode: "toggle",
  onError: (err: Error) => console.warn("[avatar]", err.message),
});

// ── Strip markdown for TTS (mirrors chat-tts.js) ──────────────────
function stripMarkdown(text: string): string {
  return text
    .replace(/<time_context>[\s\S]*?<\/time_context>/g, "")
    .replace(/<!-- msg_at:.*?-->/g, "")
    .replace(/```[\s\S]*?```/g, "コードブロック")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[*_~>#-]/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[「」（）]/g, "")
    .replace(/[―─—]/g, "。")
    .trim();
}

// ── Voice meter: mouth follows actual audio level ─────────────────
function startVoiceMeter(audioEl: HTMLAudioElement) {
  stopVoiceMeter();
  const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return;
  try {
    const ctx = new AC();
    const source = ctx.createMediaElementSource(audioEl);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analyser.connect(ctx.destination);
    const buf = new Uint8Array(analyser.frequencyBinCount);
    voiceMeter = {
      ctx,
      source,
      analyser,
      buf,
      timer: window.setInterval(() => {
        if (!voiceMeter) return;
        voiceMeter.analyser.getByteFrequencyData(voiceMeter.buf);
        let sum = 0;
        for (let i = 0; i < voiceMeter.buf.length; i++) sum += voiceMeter.buf[i];
        avatar.setMouth(sum / voiceMeter.buf.length / 255);
      }, 100),
    };
  } catch {
    // AudioContext unavailable — toggle mouth mode takes over
  }
}

function stopVoiceMeter() {
  const m = voiceMeter;
  if (!m) return;
  voiceMeter = null;
  clearInterval(m.timer);
  try {
    m.source.disconnect();
    m.analyser.disconnect();
    m.ctx.close();
  } catch {
    /* ignore */
  }
}

// ── TTS playback with mouth sync ──────────────────────────────────
async function playTts(text: string) {
  stopTts();
  if (!text) return;
  try {
    const resp = await fetch(TTS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: stripMarkdown(text) }),
    });
    const data = await resp.json();
    if (!data.audio_base64) {
      console.warn("[tts] synthesis failed:", data.error || "unknown");
      return;
    }
    const audioUrl =
      data.audio_url || `data:audio/${data.format || "wav"};base64,${data.audio_base64}`;
    const el = new Audio(audioUrl);
    el.volume = 1.0;
    audio = el;
    el.onplay = () => {
      avatar.startTalking();
      startVoiceMeter(el);
    };
    el.onended = stopTts;
    el.onerror = stopTts;
    el.play().catch((err) => {
      console.warn("[tts] autoplay blocked:", err.message);
      stopTts();
    });
  } catch (e) {
    console.warn("[tts] request failed:", e);
  }
}

function stopTts() {
  avatar.stopTalking();
  stopVoiceMeter();
  if (audio) {
    try {
      audio.pause();
    } catch {
      /* ignore */
    }
    audio.src = "";
    audio = null;
  }
}

// ── SSE chat streaming ────────────────────────────────────────────
function handleSseEvent(evt: Record<string, unknown>) {
  switch (evt.type) {
    case "text_delta": {
      const content = (evt.content as string) || "";
      fullText += content;
      bubbleText.textContent = fullText;
      bubbleText.classList.add("streaming");
      break;
    }
    case "context_update": {
      const update = evt.update as { emotion?: string; emotion_intensity?: number };
      if (update && update.emotion) {
        avatar.setEmotion(update.emotion, update.emotion_intensity ?? 1.0);
      }
      break;
    }
    case "done": {
      bubbleText.classList.remove("streaming");
      streaming = false;
      setBusy(false);
      playTts(fullText);
      break;
    }
    case "error": {
      bubbleText.classList.remove("streaming");
      streaming = false;
      setBusy(false);
      bubbleText.textContent = `エラー: ${(evt.message as string) || "不明"}`;
      break;
    }
    default:
      break;
  }
}

function setBusy(busy: boolean) {
  input.disabled = busy;
  sendBtn.disabled = busy;
}

async function sendMessage(message: string) {
  const text = message.trim();
  if (!text || streaming) return;

  streaming = true;
  fullText = "";
  bubbleText.textContent = "…";
  bubbleText.classList.add("streaming");
  setBusy(true);

  try {
    const resp = await fetch(CHAT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    if (!resp.body) throw new Error("no response body");

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // Split on SSE event boundary \n\n
      let idx = buffer.indexOf("\n\n");
      while (idx >= 0) {
        const chunk = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        for (const line of chunk.split("\n")) {
          if (!line.startsWith("data:")) continue; // skip heartbeat/comments
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            handleSseEvent(JSON.parse(payload));
          } catch {
            /* malformed JSON — skip */
          }
        }
        idx = buffer.indexOf("\n\n");
      }
    }
  } catch (e) {
    console.error("[chat] request failed:", e);
    bubbleText.classList.remove("streaming");
    streaming = false;
    setBusy(false);
    bubbleText.textContent = `エラー: ${(e as Error).message}`;
  }
}

// ── Wire up UI ────────────────────────────────────────────────────
function submit() {
  const value = input.value;
  input.value = "";
  void sendMessage(value);
}

sendBtn.addEventListener("click", submit);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") submit();
});
// Clicking the bubble focuses input (placeholder says "click to talk")
bubbleText.addEventListener("click", () => input.focus());
