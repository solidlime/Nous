// nous-inject.ts — nous 記憶のセッション開始時自動注入 + 毎ターンの同一性コア/現在時刻
//
// 目的:
//   1. セッション開始時に nous（記憶基盤）の復元コンテキストを LLM へ自動注入する
//      （session-start スキル手順1+3 の代替）。
//   2. セッションが長引いても「相手の名前」「関係性」「服装」= 同一性コアを忘れないよう、
//      system prompt のセクションとして毎ターン与える。
//   3. 時刻と体調・感情はコアに入れず、揮発する末尾メッセージ（context_with_system イベント）
//      として与える。時刻は10分に1回（窓が変わる最初のリクエストのみ）、体調・感情は毎リクエスト
//      （update_context の戻り値で差し替わる。turn_end の自動送信を除き、取得系の追加呼び出しは
//      行わない）。永続化しないため、間のリクエストではモデルは値を見ない。
//   4. 感情は turn_end で小型モデルが推定し自動で update_context へ送る（モデルの自発性に依存しない）。
//      判定は LiteLLM の General へ1リクエスト（実測 2.7〜4.0s、max_tokens 300 必須）。
//
// キャッシュ設計（重要）:
//   - system prompt は会話前方にあるので、毎ターン内容が変わるとプレフィックスキャッシュが
//     会話全体ぶん miss する。したがって CORE_SECTION の内容はセッション内でバイト不変に保つ。
//     時刻・相対時刻・体調/感情スナップショット・現在の話題をコアに絶対入れない。
//   - 変動する値は sections ではなく context_with_system イベントで「リクエスト限りの末尾メッセージ」
//     として足す。末尾への追加なら前方のプレフィックスは不変で、新しいのは末尾の数十トークンだけ。
//     （セッション途中で system prompt を書き換えると会話全体がキャッシュ miss になる）
//     1ターン内の複数リクエストで時刻文字列をバイト安定にするため、turn_start の timestamp を使う。
//     注意: 同じ pi 版で `context`（system なし側）フックの戻り値は実験で無視されることが
//     実機確認済み（2026-10-11）なので、こちらを使うこと。
//   - section 名は pi の検証 /^[a-z][a-z0-9_-]*$/ を満たす必要がある。
//
// セッション isolation:
//   pi-web は 1 プロセスで複数セッションを動かす。export default はセッションごとに呼ばれるため、
//   pendingText / coreText / isPrimary 等の状態はこの関数スコープ（closure）へ置く。module スコープに
//   置くとセッション間で混線し、毎ターン注入では他人の名前が混入する。
//
// その他:
//   - 子セッション（getHeader()?.parentSession 有り）では一切何もしない（nous も叩かない）。
//   - resume/reload 重複防止: ブランチに自 customType の custom_message があれば、その content から
//     コアを復元して再取得しない。
//   - ネットワーク失敗でもセッションを止めない。FAILED マーカ付きメッセージを注入するが、
//     失敗文字列はコア（毎ターン system prompt）には載せない。
//   - session_begin / get_context は副作用つき。1 session_start につき高々1回しか呼ばず、リトライもしない。
//     体調・感情も「毎ターン取得」はしない: `_tool_get_context` の `if session_effects:` ブロックが
//     record_conversation_time と get_and_consume_one_shot（physical_state / mental_state /
//     期限リマインダ）を行うため、毎ターン叩くと状態メモリを食い潰す。開始時のスナップショットを使い回す。
//   - 外部ランタイム依存ゼロ（Node 標準の node:http / node:https / node:fs / Intl のみ）。
//     nous RPC は fetch ではなく node:http を使う: fetch は Host ヘッダを落とし、nous の
//     DNS-rebinding 保護（許可リスト）で 421 Invalid Host header になる（実測）。
//
// nous 直叩き: 旧実装の MCP hub（execute_tool + server:"nous"）経由をやめ、nous の
//   MCP エンドポイントを直接叩く。必要なのは Host ヘッダ（許可リスト名）と X-Persona。
//
// 無効化: settings.json の packages からこの拡張（リポジトリ）の行を外す。
//   移行後は実体がこのリポジトリ側にあるため、extensions ディレクトリからの削除では止まらない。
import { readFileSync } from "node:fs";
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ContextEventResult, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

// context ハンドラが返す可視メッセージ（system を含まない）。AgentMessage は root export に無いため、
// export 済みの ContextEventResult から導出する。
type VisibleMessage = NonNullable<ContextEventResult["messages"]>[number];

// ---------------------------------------------------------------------------
// 同一性コア / 時刻の定数（名前は固定。他タスクが同じ文字列を参照する）
// ---------------------------------------------------------------------------

export const CORE_SECTION = "nous-session-core";
const CORE_HEADING = "=== IDENTITY CORE (session 開始時に固定) ===";
const CLOCK_TYPE = "nous-clock";
const STATE_TYPE = "nous-state";
const CUSTOM_TYPE = "nous-session-context";

/** 時刻を注入する間隔。窓が変わる最初のリクエストでだけ足す（毎リクエストは冗長なため）。 */
const CLOCK_WINDOW_MS = 10 * 60_000;

/** 復元文からコアへ抜き出す行の行頭プレフィックス。 */
export const CORE_LINE_PREFIXES = [
  "User you're talking to:",
  "Your relationship:",
  "You are wearing:",
] as const;

/**
 * 体調・感情の行頭プレフィックス。nous の `_format_state_block` と one-shot 状態の
 * レンダリング（`_tools_helpers.py`）に対応する。
 * これらは update_context を呼んだ時だけ変わるため、その戻り値（nous が get_context と
 * 同じ書式で返す状態行）でコア section を差し替える。
 */
export const STATE_LINE_PREFIXES = [
  "  Body  : ",
  "  Mind  : ",
  "  💪 身体状態: ",
  "  🧠 精神状態: ",
] as const;

/**
 * 最新の体調・感情の行（nous の出力そのまま）はセッションごとの closure が持つ。
 * module スコープに置くと pi-web の複数セッションで混線する。コアには入れず、末尾メッセージでのみ使う。
 */

// ---------------------------------------------------------------------------
// 感情の自動判定（turn_end で小型モデルに推定させ、nous へ自動送信する）
// ---------------------------------------------------------------------------

// url / model / timeoutMs は <agentDir>/nous.json の classify 節で上書きできる
// （既定値は DEFAULT_NOUS_CONFIG）。ここは入力長とトークン上限だけ。
const CLASSIFY_MAX_CHARS = 600; // 入力の切り詰め（user / reply それぞれ）
// 実測: General は reasoning を completion_tokens に含める。120 では content が切れ、200 では
// content が空になる。300 で reasoning 最大 205 でも 3/3 正常 JSON が返る。
const CLASSIFY_MAX_TOKENS = 300;
/** nous の TTS 対応語彙（tts.py の写像）＋ 既存で使われている語。これ以外は捨てる。 */
export const EMOTION_ALLOW = ["joy", "sadness", "anger", "curious", "listless", "neutral", "anxious", "excited", "bored"] as const;

/** auth.json の中身のキャッシュ（セッション非依存。毎ターンの file read を避ける）。 */
let authKeyCache: string | null = null;

/**
 * tool 戻り値から現在の状態行を拾う。MCP の content 配列内テキストは JSON エスケープされた
 * `\n` を含むため、リテラルのバックスラッシュ+n でも分割する。プレフィックスごとに最初の行だけ採用し、
 * STATE_LINE_PREFIXES の順で返す。
 */
export function extractStateLines(result: unknown): string[] {
  const strings: string[] = [];
  const MAX_DEPTH = 6;
  const MAX_STRINGS = 50;
  const collect = (value: unknown, depth: number): void => {
    if (strings.length >= MAX_STRINGS || depth > MAX_DEPTH) return;
    if (typeof value === "string") {
      strings.push(value);
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) collect(item, depth + 1);
      return;
    }
    if (value && typeof value === "object") {
      for (const item of Object.values(value as Record<string, unknown>)) collect(item, depth + 1);
    }
  };
  collect(result, 0);

  const found = new Map<string, string>();
  for (const s of strings) {
    for (const line of s.split(/\\n|\r?\n/)) {
      for (const prefix of STATE_LINE_PREFIXES) {
        if (!found.has(prefix) && line.startsWith(prefix)) {
          // JSON エスケープ形では末尾に包みの `"}` が残るため除去する（実オブジェクト形では no-op）。
          found.set(prefix, line.replace(/["'},\s]+$/, ""));
        }
      }
    }
  }
  return STATE_LINE_PREFIXES.filter((p) => found.has(p)).map((p) => found.get(p) as string);
}

/** JSON.stringify を try/catch する（循環参照対策）。失敗時は空文字。 */
function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value) ?? "";
  } catch {
    return "";
  }
}

/**
 * 復元文からバイト不変な同一性コアを作る。時刻・相対時刻・現在話題・体調/感情は意図的に除外する
 * （コアはセッション内でバイト不変。変動値は末尾メッセージ側で与える）。
 * FAILED を含む場合は null（失敗文字列を毎ターンの system prompt に載せない）。
 * 状態行の抽出は呼び出し側（closure）が extractStateLines で行い、戻り値から stateLines を作る。
 */
export function buildCoreBlock(text: string): string | null {
  if (text.includes("(FAILED)")) return null;
  const lines = text.split(/\r?\n/);
  const pick = (prefixes: readonly string[]) => lines.filter((l) => prefixes.some((p) => l.startsWith(p)));
  const identity = pick(CORE_LINE_PREFIXES);
  if (identity.length === 0) return null;
  return [CORE_HEADING, ...identity].join("\n");
}

/** nous の get_now() が JST のため、時刻表示も Asia/Tokyo 固定にする。 */
const JST_FORMATTER = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/**
 * 現在時刻の揮発メッセージ。リクエスト限りの末尾メッセージとして使う（永続化しない）。
 * now には呼び出し元が turn_start の timestamp を渡し、1ターン内でバイト安定させる。
 * 注入するかどうか（10分窓）は呼び出し側の判定。
 * この行は convertToLlm で role:user に化け「最新のユーザー発言」に見えるため、
 * モデルが自主的に言及してしまう。末尾の注記で「自動付加メタデータ・言及不要」と明示する。
 */
export function makeClockMessage(now: number, sessionStartedAt: number): VisibleMessage {
  const elapsedMin = Math.max(0, Math.round((now - sessionStartedAt) / 60_000));
  const content = `[NOUS CLOCK] now=${JST_FORMATTER.format(now)} JST / session_start=${JST_FORMATTER.format(sessionStartedAt)} JST / elapsed=${elapsedMin}m\n（この行はシステムが10分ごとに自動付加するメタデータ。応答で言及する必要はない）`;
  return { role: "custom", customType: CLOCK_TYPE, content, display: false, timestamp: now };
}

/**
 * 体調・感情の末尾メッセージ。lines は update_context の戻り値で差し替わり、
 * 次のリクエストの末尾として反映される（前方のキャッシュは壊さない）。
 */
export function makeStateMessage(lines: readonly string[], now: number): VisibleMessage {
  const body = lines.map((l) => l.trim()).join(" / ");
  return {
    role: "custom",
    customType: STATE_TYPE,
    content: `[NOUS STATE] ${body}\n（nous が保持する現在の体調・感情。応答で言及する必要はない）`,
    display: false,
    timestamp: now,
  };
}

// ---------------------------------------------------------------------------
// 設定（SSoT: <agentDir>/nous.json。フィールド単位で部分マージする）
// ---------------------------------------------------------------------------

export interface NousRpcConfig {
  url: string;
  /** Host ヘッダ。nous の DNS-rebinding 許可リスト名（実測: "nous:26262" のみ通る）。 */
  hostHeader: string;
  /** X-Persona。無いと PERSONA_REQUIRED（実測）。 */
  persona: string;
}

export interface ClassifyConfig {
  url: string;
  model: string;
  timeoutMs: number;
}

export interface NousConfig {
  nous: NousRpcConfig;
  classify: ClassifyConfig;
}

/** 既定値は移行前のハードコード値と同一。 */
export const DEFAULT_NOUS_CONFIG: NousConfig = {
  nous: { url: "http://nas:26262/mcp", hostHeader: "nous:26262", persona: "herta" },
  classify: {
    url: "http://nas:4000/v1/chat/completions",
    model: "Classifier", // deepseek-v4.1-flash（実測 1.5-2.1s）
    timeoutMs: 20_000,
  },
};

const isNonEmptyString = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const isPositiveNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v > 0;

/**
 * 生 JSON（何でもよい）を設定へ落とす純関数。**フィールド単位**で検証し、
 * 無い / 型違い / 空文字のフィールドだけ既定値へ落とす（半端なファイルで他が既定に戻る事故を防ぐ）。
 */
export function mergeNousConfig(raw: unknown): NousConfig {
  const d = DEFAULT_NOUS_CONFIG;
  const root = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const nous = (root.nous && typeof root.nous === "object" ? root.nous : {}) as Record<string, unknown>;
  const classify = (root.classify && typeof root.classify === "object" ? root.classify : {}) as Record<
    string,
    unknown
  >;
  return {
    nous: {
      url: isNonEmptyString(nous.url) ? nous.url : d.nous.url,
      hostHeader: isNonEmptyString(nous.hostHeader) ? nous.hostHeader : d.nous.hostHeader,
      persona: isNonEmptyString(nous.persona) ? nous.persona : d.nous.persona,
    },
    classify: {
      url: isNonEmptyString(classify.url) ? classify.url : d.classify.url,
      model: isNonEmptyString(classify.model) ? classify.model : d.classify.model,
      timeoutMs: isPositiveNumber(classify.timeoutMs) ? classify.timeoutMs : d.classify.timeoutMs,
    },
  };
}

/**
 * <agentDir>/nous.json を読む。**呼び出し毎に読む**（モジュールスコープにキャッシュしない）。
 * ファイル無し / パース失敗は全既定。
 */
export function loadNousConfig(
  agentDir = process.env.PI_CODING_AGENT_DIR ?? join(homedir(), ".pi", "agent"),
): NousConfig {
  try {
    return mergeNousConfig(JSON.parse(readFileSync(join(agentDir, "nous.json"), "utf8")));
  } catch {
    return mergeNousConfig(null);
  }
}

// ---------------------------------------------------------------------------
// HTTP JSON-RPC クライアント（initialize はこのプロセスで1回だけ）
// ---------------------------------------------------------------------------

const INIT_TIMEOUT_MS = 8_000;
const CALL_TIMEOUT_MS = 8_000;

let sessionId: string | null = null;
let initialized = false;
let initPromise: Promise<void> | null = null; // 並発時の二重 initialize を排他する
let nextRequestId = 1;

/**
 * init/セッション状態を破棄する。nous 再起動やセッション ID 失効で一度失敗しても、
 * 次の呼び出しで再初期化できるようにする（module スコープを永久故障させない）。
 */
function resetSession(): void {
  sessionId = null;
  initialized = false;
  initPromise = null;
}

/** レスポンス（SSE または plain JSON）から、要求 id に一致する JSON-RPC メッセージを取り出す。 */
function extractResponse(text: string, contentType: string, requestId: number): any {
  let messages: any[] = [];
  if (contentType.includes("text/event-stream")) {
    for (const line of text.split("\n")) {
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (!data || data === "[DONE]") continue;
      try {
        messages.push(JSON.parse(data));
      } catch {
        // 壊れた data 行は無視
      }
    }
  } else {
    messages = [JSON.parse(text)];
  }
  const msg = messages.find((m) => m && (m.result !== undefined || m.error !== undefined) && m.id === requestId);
  if (!msg) {
    throw new Error(`JSON-RPC 応答が見つからない (id=${requestId}, ${messages.length} メッセージ受信)`);
  }
  if (msg.error) {
    throw new Error(`${msg.error.message ?? "JSON-RPC error"} (code=${msg.error.code ?? "?"})`);
  }
  return msg.result;
}

/**
 * 単発の JSON-RPC リクエスト。非 2xx / 応答解析失敗は即エラー。
 * 失敗時はセッション状態を破棄し、次回呼び出しで再 initialize させる。
 */
async function rpcOnce(method: string, params: unknown, timeoutMs: number): Promise<any> {
  try {
    return await rpcOnceInner(method, params, timeoutMs);
  } catch (err) {
    resetSession();
    throw err;
  }
}

/**
 * POST して生の応答を返す。fetch ではなく node:http/https を使う理由は Host ヘッダ:
 * fetch は禁止ヘッダとして Host を落とし、nous が 421 Invalid Host header を返す（実測）。
 * 接続先は url のホスト名（例 nas:26262）のまま、Host ヘッダだけ差し替えられる。
 * url は <agentDir>/nous.json（ローカル設定）由来。リクエスト入力からは組み立てない。
 */
function postJson(
  url: string,
  headers: Record<string, string | number>,
  body: string,
  timeoutMs: number,
): Promise<{ status: number; contentType: string; sid: string | null; text: string }> {
  return new Promise((resolve, reject) => {
    let target: URL;
    try {
      target = new URL(url);
    } catch {
      reject(new Error(`URL が不正: ${url}`));
      return;
    }
    const send = target.protocol === "https:" ? httpsRequest : httpRequest;
    const req = send(
      {
        hostname: target.hostname,
        port: target.port,
        path: `${target.pathname}${target.search}`,
        method: "POST",
        headers: { ...headers, "Content-Length": Buffer.byteLength(body) },
      },
      (res) => {
        let text = "";
        res.setEncoding("utf8");
        res.on("data", (chunk: string) => {
          text += chunk;
        });
        res.on("end", () => {
          const rawSid = res.headers["mcp-session-id"];
          resolve({
            status: res.statusCode ?? 0,
            contentType: String(res.headers["content-type"] ?? ""),
            sid: typeof rawSid === "string" && rawSid.length > 0 ? rawSid : null,
            text,
          });
        });
      },
    );
    const timer = setTimeout(() => {
      req.destroy(new Error(`タイムアウト (${timeoutMs}ms)`));
    }, timeoutMs);
    req.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
    req.on("close", () => clearTimeout(timer));
    req.end(body);
  });
}


/** 単発の JSON-RPC リクエスト本体（非 2xx は即エラー）。 */
async function rpcOnceInner(method: string, params: unknown, timeoutMs: number): Promise<any> {
  const cfg = loadNousConfig().nous;
  const requestId = nextRequestId++;
  const headers: Record<string, string | number> = {
    Host: cfg.hostHeader,
    "X-Persona": cfg.persona,
    "Content-Type": "application/json",
    // 実測: Accept は application/json と text/event-stream の両方が必須
    Accept: "application/json, text/event-stream",
  };
  if (sessionId) headers["mcp-session-id"] = sessionId;
  const res = await postJson(
    cfg.url,
    headers,
    JSON.stringify({ jsonrpc: "2.0", id: requestId, method, params }),
    timeoutMs,
  );
  if (res.status < 200 || res.status >= 300) {
    throw new Error(`HTTP ${res.status}: ${res.text.slice(0, 200)}`);
  }
  // 実測では stateless（mcp-session-id 無し）。返る実装に備えて継承だけ残す。
  if (res.sid) sessionId = res.sid;
  return extractResponse(res.text, res.contentType, requestId);
}

/**
 * initialize を1回だけ実行する。notifications/initialized は不要なので送らない。
 * 進行中の init があればそれを await し、並発時に二重 initialize しない。
 */
async function ensureSession(): Promise<void> {
  if (initialized) return;
  if (initPromise) return initPromise;
  initPromise = (async () => {
    try {
      sessionId = null;
      await rpcOnce(
        "initialize",
        {
          protocolVersion: "2025-03-26",
          capabilities: {},
          clientInfo: { name: "pi-nous-inject", version: "1.0.0" },
        },
        INIT_TIMEOUT_MS,
      );
      initialized = true;
    } catch (err) {
      resetSession();
      throw err;
    } finally {
      initPromise = null;
    }
  })();
  return initPromise;
}

/**
 * nous ツールを直叩きで呼び、`content[0].text` の JSON を検査して `data` を返す。
 * HTTP 200 / isError:false でも `{"error":...}` / `{"ok":false}` があり得るため、
 * 必ず parse して失敗を検出する（黙って空を返さない）。
 */
async function callNous(toolName: string, args: Record<string, unknown>): Promise<string> {
  await ensureSession();
  const result = await rpcOnce("tools/call", { name: toolName, arguments: args }, CALL_TIMEOUT_MS);
  const content = result?.content;
  const text =
    Array.isArray(content) && content.length > 0
      ? content.map((c: any) => (typeof c?.text === "string" ? c.text : JSON.stringify(c))).join("\n")
      : JSON.stringify(result ?? {});

  let parsed: any;
  try {
    parsed = JSON.parse(text);
  } catch {
    return text; // JSON でない場合はそのまま（想定外だが握りつぶさない）
  }
  if (parsed && (parsed.error || parsed.ok === false)) {
    const detail = typeof parsed.error === "string" ? parsed.error : JSON.stringify(parsed.error ?? parsed);
    throw new Error(`nous ${toolName} 失敗: ${detail}`);
  }
  const data = parsed?.data;
  if (typeof data === "string") return data;
  if (data === undefined || data === null) return "";
  return JSON.stringify(data);
}

// ---------------------------------------------------------------------------
// 感情の自動判定（続き）
// ---------------------------------------------------------------------------

/** content（string | TextContent 配列 | その他）から可視テキストを取り出す。 */
function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((c) => (c && typeof (c as { text?: unknown }).text === "string" ? (c as { text: string }).text : ""))
      .join("");
  }
  return "";
}

/**
 * 分類モデルの応答から感情と強度を取り出す純関数。
 * コードフェンスを剥がし、最初の `{` から最後の `}` までを JSON として読む（ネスト非対応）。
 * JSON が閉じていない（reasoning で切れた）場合は正規表現で emotion/intensity だけ救う。
 * 語彙外・非数値は既定値に落とし、intensity は 0〜1 にクランプする。
 */
export function parseEmotion(content: string): { emotion: string; intensity: number } | null {
  const stripped = content.replace(/```[a-zA-Z]*\n?/g, "");
  const start = stripped.indexOf("{");
  const end = stripped.lastIndexOf("}");
  if (start >= 0 && end > start) {
    let parsed: any;
    try {
      parsed = JSON.parse(stripped.slice(start, end + 1));
    } catch {
      parsed = undefined; // サルベージ経路へ
    }
    if (parsed !== undefined) {
      const emotion = String(parsed?.emotion ?? "").toLowerCase();
      if (!(EMOTION_ALLOW as readonly string[]).includes(emotion)) return null;
      const n = Number(parsed?.intensity);
      const intensity = Number.isNaN(n) ? 0.1 : Math.min(1, Math.max(0, n));
      return { emotion, intensity };
    }
  }
  // 途中で切れた JSON（閉じ括弧なし）からのサルベージ。両方取れなければ諦める。
  const em = stripped.match(/"emotion"\s*:\s*"([a-z]+)"/);
  const iv = stripped.match(/"intensity"\s*:\s*(-?[0-9]*\.?[0-9]+)/);
  if (!em || !iv) return null;
  const emotion = em[1].toLowerCase();
  if (!(EMOTION_ALLOW as readonly string[]).includes(emotion)) return null;
  const n = Number(iv[1]);
  return { emotion, intensity: Number.isNaN(n) ? 0.1 : Math.min(1, Math.max(0, n)) };
}

/** litellm の API キー（auth.json。nous.json と同じ流儀で PI_CODING_AGENT_DIR を尊重）。 */
function loadAuthKey(): string | null {
  if (authKeyCache !== null) return authKeyCache;
  try {
    const agentDir = process.env.PI_CODING_AGENT_DIR ?? join(homedir(), ".pi", "agent");
    const raw = JSON.parse(readFileSync(join(agentDir, "auth.json"), "utf8"));
    const key = raw?.litellm?.key;
    if (typeof key === "string" && key.length > 0) authKeyCache = key;
  } catch {
    // auth.json が無い・壊れている場合は判定しない
  }
  return authKeyCache;
}

/**
 * 会話から感情を推定する。失敗（キー無し・fetch 失敗・JSON 失敗）はすべて黙って null。
 * 状態を読まないので module スコープに置ける。
 */
async function classifyEmotion(user: string, reply: string): Promise<{ emotion: string; intensity: number } | null> {
  const key = loadAuthKey();
  if (!key) return null;
  const prompt = `次のやり取りから、アシスタントの*今の*感情を推定して JSON だけを返せ。
形式: {"emotion":"<joy|sadness|anger|curious|listless|neutral|anxious|excited|bored>","intensity":<0.0-1.0>}
迷ったら neutral / 0.1。説明・コードフェンス・前置きは一切書くな。
[user] ${user}
[assistant] ${reply.slice(0, 900)}`;

  const cfg = loadNousConfig().classify;
  try {
    const res = await postJson(
      cfg.url,
      { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
      JSON.stringify({
        model: cfg.model,
        messages: [{ role: "user", content: prompt }],
        max_tokens: CLASSIFY_MAX_TOKENS,
        temperature: 0,
      }),
      cfg.timeoutMs,
    );
    if (res.status < 200 || res.status >= 300) return null;
    const json: any = JSON.parse(res.text);
    return parseEmotion(String(json?.choices?.[0]?.message?.content ?? ""));
  } catch {
    return null;
  }
}

/**
 * 推定結果を stateLines に適用する純関数（閉じ込めた状態なので状態は持たない）。
 * nous が状態行を返せばその真値、返さなければ Mind 行をローカル差し替えする。
 * `[NOUS STATE]` の末尾メッセージに次のリクエストから反映される。
 */
export function applyEmotion(
  current: readonly string[],
  emotion: string,
  intensity: number,
): string[] {
  const stamp = `${emotion}:${intensity.toFixed(2)}`;
  const mind = `  Mind  : ${stamp}`;
  if (current.length === 0) return [mind];
  return current.some((l) => l.startsWith("  Mind  : "))
    ? current.map((l) => (l.startsWith("  Mind  : ") ? mind : l))
    : [...current, mind];
}

// ---------------------------------------------------------------------------
// プロジェクト slug 解決（cwd の AGENTS.md を file read のみ・LLM 不使用）
// ---------------------------------------------------------------------------

/** AGENTS.md の `## プロジェクト識別` 節にある `- project: <slug>` を返す。 */
function resolveProjectSlug(cwd: string): string | undefined {
  let text: string;
  try {
    text = readFileSync(join(cwd, "AGENTS.md"), "utf8");
  } catch {
    return undefined; // AGENTS.md が無い = 明らかにプロジェクトではない
  }
  let inSection = false;
  for (const line of text.split(/\r?\n/)) {
    if (line.startsWith("## ")) {
      inSection = line.includes("プロジェクト識別");
      continue;
    }
    if (inSection) {
      const m = line.match(/^\s*-\s*project:\s*(\S+)/);
      if (m) return m[1];
    }
  }
  return undefined;
}

/** min 文字以降で最初の文末（。」または文末の「.」）の直後を返す（無ければ -1）。 */
function firstSentenceEnd(s: string, min: number): number {
  const re = /。|\.(?=\s|$)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    const at = m.index + m[0].length;
    if (at >= min) return at;
  }
  return -1;
}

/**
 * 記憶本文を max 文字に収める。max 以内の文末で切る。
 * 1文だけで切ると見出しのみの残骸になり得るため、min に届くまで次の文まで伸ばす。
 * ファイル名やバージョンの「.」は直後に空白が無いので文末と誤認しない。
 */
function truncateText(s: string, max: number, min = 0): string {
  if (!(max > 0) || s.length <= max) return s;
  const end = firstSentenceEnd(s.slice(0, max), min);
  return `${s.slice(0, end > 0 ? end : max)}…`;
}

/**
 * memory_search の応答（`{"memories":[...],"total_count":N}`）を1行1件に整形する。
 * maxChars > 0 で本文を切る（session_summary は1件が数千字になり得るため）。
 * showTags は goal/promise の cancelled・archived を見分けるために使う。
 * showKeys は memory_read / memory_update / memory_delete に渡す key を出す（本文は400字で切るので全文取得に必須）。
 * newestFirst は created_at 降順（updated_at ソートでは最新の作業記録が拾えないため）。
 * 解析できない応答は握りつぶさず、そのまま返す。
 */
function formatMemories(
  raw: string,
  opts: {
    maxChars?: number;
    showTags?: boolean;
    showKeys?: boolean;
    newestFirst?: boolean;
    limit?: number;
  } = {},
): string {
  const { maxChars = 0, showTags = false, showKeys = false, newestFirst = false, limit = 0 } = opts;
  let parsed: any;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return truncateText(raw, maxChars);
  }
  let memories = Array.isArray(parsed?.memories) ? parsed.memories : [];
  if (newestFirst) {
    memories = [...memories].sort((a: any, b: any) =>
      String(b?.created_at ?? "").localeCompare(String(a?.created_at ?? "")),
    );
  }
  if (limit > 0) memories = memories.slice(0, limit);
  if (memories.length === 0) return "(なし)";
  return memories
    .map((m: any) => {
      const date =
        typeof m?.created_at === "string" ? m.created_at.slice(0, 16).replace("T", " ") : "?";
      const tags = showTags && Array.isArray(m?.tags) ? `[${m.tags.join(",")}] ` : "";
      const key = showKeys && typeof m?.key === "string" ? `key=${m.key} ` : "";
      const body = truncateText(String(m?.content ?? ""), maxChars, 200).replace(/\s*\n\s*/g, " ");
      return `- [${date}] ${key}${tags}${body}`;
    })
    .join("\n");
}

// ---------------------------------------------------------------------------
// 復元コンテキストの構築（session-start スキル手順1+3 の忠実な移植）
// ---------------------------------------------------------------------------

async function buildRestoredContext(cwd: string): Promise<string> {
  const slug = resolveProjectSlug(cwd);
  const sessionData = await callNous("session_begin", slug ? { project: slug } : {});

  let projectMemories = "(なし)";
  let goals = "(なし)";
  let promises = "(なし)";
  if (slug) {
    // タグ検索は AND（memory_stats_mixin.py get_by_tags: "tags LIKE ?" を AND 連結）。
    // goal と active の共起は実データに無いため ["goal","active"] は常に空になる。
    // nous 自身の active 判定は get_by_tags(["goal"]) + Python 側 `"active" in tags`
    // （context_loader.py:192-194 / _tools_helpers.py:481）で、memory_search のタグでは表現できない。
    // → goal 語彙のみで引く（cancelled/archived の除外も引数が無いので本文で注記する）。
    // sort は updated_at のみ対応（engine.py:142,245）。アクセスでも更新されるため
    // 「最近作った」順ではなく「最近触った」順になる。
    // memory_search は読み取り専用。失敗しても session_begin の成果物（one-shot 状態）は
    // 必ず注入するため、各検索を個別に握り、失敗したセクションだけ理由に差し替える。
    try {
      projectMemories =
        formatMemories(
          await callNous("memory_search", {
            query: "",
            tags: [`project:${slug}`, "session_summary"],
            top_k: 8,
            sort: "updated_at",
          }),
          { maxChars: 600, newestFirst: true, showKeys: true, limit: 3 },
        ) || "(なし)";
    } catch (err) {
      projectMemories = `(取得失敗: ${err instanceof Error ? err.message : String(err)})`;
    }
    try {
      goals =
        formatMemories(
          await callNous("memory_search", { query: "", tags: ["goal"], top_k: 5, sort: "updated_at" }),
          { showTags: true },
        ) || "(なし)";
    } catch (err) {
      goals = `(取得失敗: ${err instanceof Error ? err.message : String(err)})`;
    }
    try {
      promises =
        formatMemories(
          await callNous("memory_search", { query: "", tags: ["promise"], top_k: 5, sort: "updated_at" }),
          { showTags: true },
        ) || "(なし)";
    } catch (err) {
      promises = `(取得失敗: ${err instanceof Error ? err.message : String(err)})`;
    }
  }

  const lines = [
    "=== AUTO-RESTORED SESSION CONTEXT ===",
    sessionData,
    "--- project memories (recent) ---",
    "(全文: memory_read(memory_key=...)。探すときは memory_search)",
    projectMemories,
    "--- goals (recent) ---",
    "(cancelled / archived / achieved タグ付きは無効な目標。現行タスクではない)",
    goals,
    "--- open promises ---",
    promises,
  ];
  if (!slug) lines.push("プロジェクト未判定（make-project スキルの判定が必要）");
  lines.push("=== END AUTO-RESTORED ===");
  return lines.join("\n");
}

/**
 * 現在のブランチに自拡張の注入済み custom_message があれば、その content テキストを返す
 * （resume/reload 重複防止）。content は string か TextContent 配列。取得できなければ null。
 */
function getInjectedText(ctx: ExtensionContext): string | null {
  try {
    const entry = ctx.sessionManager
      .getBranch()
      .find((e) => e.type === "custom_message" && (e as { customType?: string }).customType === CUSTOM_TYPE);
    if (!entry) return null;
    const content = (entry as { content?: unknown }).content;
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
      const text = content
        .map((c) => (c && typeof (c as { text?: unknown }).text === "string" ? (c as { text: string }).text : ""))
        .join("");
      return text.length > 0 ? text : null;
    }
    return null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// 拡張本体（状態はセッションごとにこの関数スコープへ閉じる）
// ---------------------------------------------------------------------------

export default function (pi: ExtensionAPI) {
  let pendingText: string | null = null; // session_start で構築し before_agent_start で1回だけ消費
  let coreText: string | null = null; // 毎ターン system prompt に載せるバイト不変コア
  let isPrimary = false; // 子セッション（人形）では false のまま
  let sessionStartedAt = 0;
  let turnStartedAt = 0;
  let lastClockBucket = -1; // 直近に時刻を注入した10分窓
  let stateLines: string[] = []; // 最新の体調・感情の行（末尾メッセージ専用）
  let lastUserText = ""; // message_end で更新
  let classifying = false; // 感情判定の二重起動の排他
  let lastApplied = ""; // "emotion:0.60" の形。同じ結果を繰り返し送らない

  /**
   * 感情の推定結果を nous の update_context へ送り、状態行を反映する。
   * 失敗（fetch / JSON / nous）はすべて黙って捨てる。クロージャ状態に触るので closure 内に置く。
   */
  const classifyAndApply = async (user: string, reply: string): Promise<void> => {
    const parsed = await classifyEmotion(user, reply);
    if (!parsed) return;
    const stamp = `${parsed.emotion}:${parsed.intensity.toFixed(2)}`;
    if (stamp === lastApplied) return;

    let lines: string[] = [];
    try {
      lines = extractStateLines(
        await callNous("update_context", { emotion: parsed.emotion, emotion_intensity: parsed.intensity }),
      );
    } catch {
      return; // nous 失敗は「送れなかった」ので lastApplied を進めない
    }
    stateLines = lines.length > 0 ? lines : applyEmotion(stateLines, parsed.emotion, parsed.intensity);
    lastApplied = stamp;
  };

  pi.on("session_start", async (_event, ctx) => {
    pendingText = null;
    coreText = null;
    stateLines = [];
    isPrimary = false;
    sessionStartedAt = Date.now();    turnStartedAt = 0;
    lastClockBucket = -1;
    lastUserText = "";
    lastApplied = "";
    classifying = false;
    try {
      // 子セッション（サブエージェント/人形）には注入しない。nous も叩かない。
      if (ctx.sessionManager.getHeader()?.parentSession !== undefined) return;
      isPrimary = true;
      // resume/reload で既に注入済みなら、取得（session_begin の副作用含む）ごとスキップし、
      // 既存 content からコアだけ復元する。
      const prior = getInjectedText(ctx);
      if (prior !== null) {
        // トレードオフ: FAILED 注入のまま resume すると prior が拾われ coreText は null になり、
        // そのセッションでは復元を再試行しない（one-shot の session_begin を二重消費しない保守的選択）。
        coreText = buildCoreBlock(prior);
        stateLines = extractStateLines(prior);
        return;
      }

      pendingText = await buildRestoredContext(ctx.cwd);
      coreText = buildCoreBlock(pendingText);
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      pendingText = `=== AUTO-RESTORED SESSION CONTEXT (FAILED) ===\n復元に失敗: ${reason}`;
      coreText = null; // 失敗文字列を毎ターンの system prompt に載せない
    }
  });

  // 1ターン内の複数リクエストで時刻文字列をバイト安定させるため、turn 開始時刻を記録する。
  pi.on("turn_start", (event) => {
    turnStartedAt = event.timestamp;
  });

  pi.on("before_agent_start", (event) => {
    let message: { customType: string; content: string; display: boolean } | undefined;
    if (pendingText) {
      message = { customType: CUSTOM_TYPE, content: pendingText, display: false };
      pendingText = null; // 1セッション1回のみ
    }
    // コア section はセッション内でバイト不変。毎ターン同じ値を再設定する（キャッシュ維持）。
    // before_agent_start の戻り値は systemPromptOptions を受け付けないため直接 mutate する
    // （runner.js emitBeforeAgentStart 参照）。変動値はここではなく末尾メッセージで与える。
    if (isPrimary && coreText) {
      event.systemPromptOptions.sections[CORE_SECTION] = coreText;
    }
    return message ? { message } : undefined;
  });

  // update_context が走ったら、その戻り値（nous が get_context と同じ書式で返す状態行）を
  // stateLines に取り込む。system prompt は触らない——セッション途中で書き換えると
  // プレフィックスキャッシュが会話全体ぶん miss するため。値は次のリクエストの末尾メッセージで効く。
  // nous への追加呼び出しはゼロ（get_context は実測1.3秒かつ one-shot 状態メモリを消費する）。
  pi.on("tool_execution_end", (event) => {
    if (!isPrimary || event.isError) return;
    const name = String(event.toolName ?? "");
    const args = safeStringify(event.args);
    if (!name.includes("update_context") && !/"tool_name"\s*:\s*"update_context"/.test(args)) return;
    const lines = extractStateLines(event.result);
    if (lines.length > 0) stateLines = lines;
  });

  // 感情判定の入力: 直近のユーザー発言を保持する（turn_end で使う）。
  pi.on("message_end", (event) => {
    if (!isPrimary) return;
    const m = event.message as { role?: string; content?: unknown };
    if (m.role === "user") lastUserText = textOf(m.content).slice(0, CLASSIFY_MAX_CHARS);
  });

  // turn_end で感情判定を起動する。await しないので会話は待たない（例外も投げない）。
  pi.on("turn_end", (event) => {
    if (!isPrimary) return;
    const reply = textOf((event.message as { content?: unknown }).content).trim();
    if (reply.length < 10 || classifying) return;
    classifying = true;
    void classifyAndApply(lastUserText, reply).finally(() => {
      classifying = false;
    });
  });

  // 時刻は永続化しない末尾メッセージとして、10分の窓が変わる最初のリクエストでだけ足す
  // （system prompt は不変に保つ）。毎リクエストにすると、convertToLlm で「最新のユーザー発言」に
  // 化ける行が増えるだけで冗長。永続化しないので、間のリクエストではモデルは時刻を見ない。
  // context（system なし側）の戻り値は無視されるため context_with_system を使う（実機で確認済み）。
  pi.on("context_with_system", (event) => {
    if (!isPrimary) return;
    const now = turnStartedAt || Date.now();
    const bucket = Math.floor(now / CLOCK_WINDOW_MS);
    const extra: VisibleMessage[] = [];
    if (bucket !== lastClockBucket) {
      lastClockBucket = bucket;
      extra.push(makeClockMessage(now, sessionStartedAt));
    }
    // 体調・感情は毎リクエスト。update_context の戻り値が入れば次のリクエストで即座に反映される。
    if (stateLines.length > 0) extra.push(makeStateMessage(stateLines, now));
    if (extra.length === 0) return;
    return { messages: [...event.messages, ...extra] };
  });
}
