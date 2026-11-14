// nous-events.ts — pi のセッション/ターン境界を nous の /api/events/ingest へ転送する観測専用拡張
//
// 目的:
//   pi の MCP 経由対話（nous の chat pipeline を通らない）を、pi の自律判断と無関係に
//   nous 側へ流す。記憶の抽出・整形は nous 側 hook pipeline / freshness worker が行う。
//   この拡張は「観測と転送」に徹し、記憶判断はしない（tool-observer.ts と同じ不変条件）。
//
// 不変条件:
//   - tool 引数の原文・tool output の本文は絶対に送らない。送るのは path/line レベルの薄いメタのみ。
//   - assistant/user 本文は nous 側の抽出入力としてのみ送る（4000 字 ellipsize）。
//   - 例外を投げない。全ハンドラ try/catch、失敗は console.error 1 行（作業を止めない）。
//   - API key / token はログ・ファイルへ書かない（Authorization ヘッダのみ）。
//   - factory 内ではネットワーク・ソケット・タイマ・watcher を開かない（セッション無しでもロードされる）。
//     設定解決と送信は session_start 以降。
//
// 無効化: このファイルを ~/.pi/agent/extensions/ から削除すれば自動探索されない。
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { type ExtensionAPI, getAgentDir } from "@earendil-works/pi-coding-agent";

const DEFAULT_ENDPOINT = "http://nas:26262/api/events/ingest";
const DEFAULT_PERSONA = "herta";
const MAX_TEXT = 4000; // nous 側 _ellipsize と同じ上限
const MAX_SUMMARY = 160;
const MAX_TOOL_LOG = 50; // 1 turn で送る tool_calls_log の上限
const TIMEOUT_MS = 8000;
const RECALL_TIMEOUT_MS = 6000;
// 短すぎる発話（「進めて」等）は語彙が足りず無関係な記憶を引くので、projectSlug を足して検索する。
const MIN_QUERY_CHARS = 20;
// 注入する wiki ページの上限（生記憶より少なくする — ページは本文が長い）。
const WIKI_TOP_K = 2;
const MAX_QUERY = 300; // recall クエリとして nous に送る上限字数
const MAX_RECALL_CONTENT = 400; // 注入する各記憶本文の上限字数

// ---------------------------------------------------------------------------
// 純関数（export は自己チェック用。拡張の実行には影響しない）
// ---------------------------------------------------------------------------

/** 文字列化して max 字で切り詰める（省略記号付き）。 */
export function ellipsize(value: unknown, max = MAX_TEXT): string {
  const text = typeof value === "string" ? value : "";
  return text.length <= max ? text : `${text.slice(0, max)}…`;
}

/** user/assistant メッセージから本文テキストのみ抽出（thinking / toolCall / image は捨てる）。 */
export function textOf(message: any): string {
  const content = message?.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part: any) => part && part.type === "text" && typeof part.text === "string")
    .map((part: any) => part.text as string)
    .join("\n");
}

const PATH_KEYS = ["path", "file_path", "filePath", "file", "filename", "notebook_path"];
const LINE_KEYS = ["line", "start_line", "end_line", "startLine", "endLine", "offset", "limit"];

/**
 * tool 引数から path/line レベルの薄いメタだけを作る。
 * 本文・コマンド・pattern・content 等は絶対に含めない（tool-observer.ts の不変条件に合わせる）。
 */
export function argsSummary(args: unknown): string {
  if (!args || typeof args !== "object" || Array.isArray(args)) return "";
  const obj = args as Record<string, unknown>;
  const parts: string[] = [];
  for (const key of PATH_KEYS) {
    const value = obj[key];
    if (typeof value === "string" && value) {
      parts.push(ellipsize(value, 120));
      break;
    }
  }
  const lines = LINE_KEYS.filter((key) => typeof obj[key] === "number").map((key) => `${key}=${obj[key]}`);
  if (lines.length > 0) parts.push(lines.join(","));
  return ellipsize(parts.join(" "), MAX_SUMMARY);
}

/** 設定ファイルの簡易パース（壊れていても例外を出さない）。 */
function readJson(path: string): any {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

/** .env 形式の 1 キー読み取り（無ければ空文字）。secret はログに出さない。 */
export function readEnvValue(path: string, keys: string[]): string {
  try {
    for (const raw of readFileSync(path, "utf8").split(/\r?\n/)) {
      const m = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/.exec(raw);
      if (!m || !keys.includes(m[1])) continue;
      let value = m[2].trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      if (value) return value;
    }
  } catch {
    // 読めない .env は無視
  }
  return "";
}

// ---------------------------------------------------------------------------
// project slug: cwd の AGENTS.md から `project: <slug>` 1行を検出する
// ---------------------------------------------------------------------------

/**
 * AGENTS.md の `project: <slug>` 1 行から slug を抽出する。
 * canonical 規約はサーバ側 `nous/domain/value_objects.py:normalize_project_slug` と同一
 * （lowercase 化 → `_`/空白を `-` に → `[a-z0-9][a-z0-9-]*` でなければ空）。
 * 緩い検証だとサーバで正規化されて効く slug が拡張側で捨てられ、ブーストが丸ごと消える。
 */
const PROJECT_SLUG_RE = /^[a-z0-9][a-z0-9-]*$/;

export function resolveProject(cwd: string): string {
  try {
    const text = readFileSync(join(cwd, "AGENTS.md"), "utf8");
    for (const line of text.split(/\r?\n/)) {
      const m = /^[ \t]*-?[ \t]*project:[ \t]*(\S*)[ \t]*(?:#.*)?$/.exec(line);
      if (!m) continue;
      return normalizeProjectSlug(m[1]);
    }
    return "";
  } catch {
    return "";
  }
}

/** サーバ側 normalize_project_slug と同じ規則（差があるとブーストが無言で消える）。 */
export function normalizeProjectSlug(value: string): string {
  const slug = value.trim().toLowerCase().replace(/[\s_]+/g, "-");
  return PROJECT_SLUG_RE.test(slug) ? slug : "";
}

// ---------------------------------------------------------------------------
// recall (push 自動注入): user prompt に対する nous 類似検索を LLM request 直前の
// custom message として差し込む。設定は nous.json の nous.recall で制御する。
// ---------------------------------------------------------------------------

export interface RecallHit {
  content: string;
  kind: string;
  score: number;
  created: string;
}

/** 編纂済み wiki ページのヒット（``payload.wiki``）。 */
export interface RecallWikiHit {
  slug: string;
  title: string;
  excerpt: string;
  score: number;
}

/** /api/search/{persona} の応答から wiki ヒットを抽出（壊れていれば空配列）。 */
export function parseWikiPayload(payload: unknown, topK: number): RecallWikiHit[] {
  const rows = (payload as any)?.wiki;
  if (!Array.isArray(rows)) return [];
  const hits: RecallWikiHit[] = [];
  for (const row of rows) {
    const slug = typeof (row as any)?.slug === "string" ? (row as any).slug : "";
    if (!slug) continue;
    const raw = (row as any)?.score;
    const score = typeof raw === "number" ? raw : Number(raw);
    const title = typeof (row as any)?.title === "string" && (row as any).title ? (row as any).title : slug;
    const excerpt = typeof (row as any)?.excerpt === "string" ? (row as any).excerpt : "";
    hits.push({
      slug,
      title,
      excerpt: ellipsize(excerpt.replace(/\s+/g, " ").trim(), MAX_RECALL_CONTENT),
      score: Number.isFinite(score) ? Math.round(score * 100) / 100 : 0,
    });
    if (hits.length >= topK) break;
  }
  return hits;
}

/** /api/search/{persona} の応答から注入対象を抽出（壊れていれば空配列）。 */
export function parseRecallPayload(payload: unknown, minScore: number, topK: number): RecallHit[] {
  const rows = (payload as any)?.results;
  if (!Array.isArray(rows)) return [];
  const hits: RecallHit[] = [];
  for (const row of rows) {
    const memory = (row as any)?.memory;
    const content = typeof memory?.content === "string" ? memory.content.trim() : "";
    if (!content) continue;
    const score = typeof row?.score === "number" ? row.score : Number(row?.score);
    if (!Number.isFinite(score) || score < minScore) continue;
    hits.push({
      content: ellipsize(content.replace(/\s+/g, " ").trim(), MAX_RECALL_CONTENT),
      kind: typeof memory.kind === "string" ? memory.kind : "",
      score: Math.round(score * 100) / 100,
      created: typeof memory.created_at === "string" ? memory.created_at.slice(0, 10) : "",
    });
    if (hits.length >= topK) break;
  }
  return hits;
}

/** recall に送るクエリを組み立てる。短い発話は projectSlug を語彙として足す。 */
export function buildRecallQuery(prompt: string, projectSlug: string): string {
  const text = prompt.replace(/\s+/g, " ").trim();
  if (!text) return "";
  if (text.length < MIN_QUERY_CHARS && projectSlug) return `${text} ${projectSlug}`;
  return text;
}

/** 注入する custom message 本文を組み立てる。 */
export function formatRecall(hits: RecallHit[], wiki: RecallWikiHit[] = []): string {
  const lines: string[] = ["[nous recall] 直近のユーザー発言に関連する過去の記憶:"];
  if (wiki.length > 0) {
    lines.push("📚 Wiki:");
    wiki.forEach((hit, i) => {
      lines.push(`${i + 1}. (${hit.score}) ${hit.title} [${hit.slug}] ${hit.excerpt}`);
    });
  }
  if (hits.length > 0) {
    lines.push("💭 記憶:");
    hits.forEach((hit, i) => {
      const bits: string[] = [`(${hit.score})`];
      if (hit.kind) bits.push(hit.kind);
      if (hit.created) bits.push(hit.created);
      lines.push(`${i + 1}. ${bits.join(" ")} ${hit.content}`);
    });
  }
  lines.push("---");
  lines.push(
    "上記は nous の記憶保管所から自動で引いたもの。さらに引くには nous MCP の memory_search（生記憶）/ wiki_grep・wiki_read（編纂済みページ）を使う。",
  );
  return lines.join("\n");
}

interface RecallConfig {
  enabled: boolean;
  topK: number;
  /** REST /api/search の composite スコアで切る最低値（0 = フィルタ無効。尺度が非正規化なので既定は無効）。 */
  minScore: number;
}

interface HookConfig {
  endpoint: string;
  apiKey: string;
  persona: string;
  recall: RecallConfig;
}

/**
 * 設定解決: env → ~/.pi/agent/nous.json → cwd/.env。
 * nous.json の URL は MCP 用（/mcp）なので origin だけ流用して ingest パスを組み立てる。
 */
export function resolveConfig(): HookConfig {
  const nousEnv: any = readJson(join(getAgentDir(), "nous.json"));
  const nous: any = nousEnv && typeof nousEnv === "object" ? (nousEnv.nous ?? nousEnv) : {};

  let endpoint = process.env.NOUS_HOOK_URL || "";
  if (!endpoint && typeof nous?.url === "string" && nous.url) {
    try {
      endpoint = `${new URL(nous.url).origin}/api/events/ingest`;
    } catch {
      endpoint = "";
    }
  }
  if (!endpoint) endpoint = DEFAULT_ENDPOINT;

  const envFile = process.env.NOUS_ENV_FILE || join(process.cwd(), ".env");
  const apiKey =
    process.env.NOUS_PLUGIN_API_KEY ||
    process.env.NOUS_PLUGIN__API_KEY ||
    (typeof nous?.apiKey === "string" ? nous.apiKey : "") ||
    (typeof nous?.api_key === "string" ? nous.api_key : "") ||
    readEnvValue(envFile, ["NOUS_PLUGIN__API_KEY", "NOUS_PLUGIN_API_KEY"]);

  const persona = process.env.NOUS_PERSONA || (typeof nous?.persona === "string" ? nous.persona : "") || DEFAULT_PERSONA;

  const recallRaw: any = nous?.recall;
  const recall: RecallConfig = { enabled: recallRaw?.enabled === true, topK: 3, minScore: 0 };
  if (typeof recallRaw?.top_k === "number" && Number.isFinite(recallRaw.top_k)) {
    recall.topK = Math.max(1, Math.min(10, Math.round(recallRaw.top_k)));
  }
  if (typeof recallRaw?.min_score === "number" && Number.isFinite(recallRaw.min_score)) {
    recall.minScore = Math.max(0, Math.min(1, recallRaw.min_score));
  }

  return { endpoint, apiKey: apiKey.trim(), persona, recall };
}

// ---------------------------------------------------------------------------
// 拡張本体（状態はセッションごとにこの関数スコープへ閉じる）
// ---------------------------------------------------------------------------

interface ToolLog {
  tool: string;
  args_summary: string;
  ok: boolean;
  ms: number | null;
}

export default function nousEvents(pi: ExtensionAPI): void {
  let sessionId = randomUUID();
  let config: HookConfig = {
    endpoint: DEFAULT_ENDPOINT,
    apiKey: "",
    persona: DEFAULT_PERSONA,
    recall: { enabled: false, topK: 3, minScore: 0 },
  };
  let warnedNoKey = false;
  let userText = "";
  let turnSeq = 0;
  let lastFlushedTurn = -1; // 同一ターンの二重送信防止（idempotency key = turn 番号）
  let assistantTexts: string[] = [];
  let projectSlug = "";
  let tools: ToolLog[] = [];
  const pendingTools = new Map<string, { tool: string; args_summary: string }>();
  const inflight = new Set<Promise<void>>();

  function logFailure(message: string): void {
    try {
      console.error(`[nous-events] ${message}`);
    } catch {
      // stderr 失敗も握りつぶす
    }
  }

  /** fire-and-forget POST。失敗は 1 行ログ、例外は外へ出さない。 */
  function post(events: unknown[]): void {
    if (!config.apiKey) return;
    const body = JSON.stringify({ session_id: sessionId, persona: config.persona, events });
    const task = (async () => {
      try {
        const res = await fetch(config.endpoint, {
          method: "POST",
          headers: { "content-type": "application/json", authorization: `Bearer ${config.apiKey}` },
          body,
          signal: AbortSignal.timeout(TIMEOUT_MS),
        });
        if (!res.ok) logFailure(`ingest HTTP ${res.status}`);
      } catch (err) {
        logFailure(`post failed: ${err instanceof Error ? err.message : String(err)}`);
      }
    })();
    inflight.add(task);
    void task.finally(() => inflight.delete(task));
  }

  function makeEvent(type: string, summary: string, detail: unknown): Record<string, unknown> {
    return { type, timestamp: new Date().toISOString(), summary, detail, metadata: null };
  }

/** nous の関連記憶検索（GET /api/search/{persona}）。失敗は throw（呼び出し元で握る）。 */
  async function fetchRecall(query: string, limit: number, project: string): Promise<unknown> {
    const base = new URL(config.endpoint).origin;
    const suffix = project ? `&project=${encodeURIComponent(project)}` : "";
    const url = `${base}/api/search/${encodeURIComponent(config.persona)}?q=${encodeURIComponent(query)}&limit=${limit}${suffix}`;
    const res = await fetch(url, {
      headers: { authorization: `Bearer ${config.apiKey}` },
      signal: AbortSignal.timeout(RECALL_TIMEOUT_MS),
    });
    if (!res.ok) throw new Error(`search HTTP ${res.status}`);
    return (await res.json()) as unknown;
  }

  /**
   * 現在のユーザーターン分を turn.completed として送る（同一ターンは 1 回だけ。idempotency key = turn 番号）。
   */
  function flushTurn(): void {
    const user = userText;
    const assistant = assistantTexts.join("\n\n");
    if (!user && !assistant) return;
    if (lastFlushedTurn === turnSeq) return;
    lastFlushedTurn = turnSeq;

    const toolLog = tools.slice(-MAX_TOOL_LOG);
    // userText は次の user メッセージまで保持（continuation ターンでも文脈を失わない）
    assistantTexts = [];
    tools = [];
    pendingTools.clear();

    const head = user.replace(/\s+/g, " ").trim();
    post([
      makeEvent("turn.completed", `turn: ${ellipsize(head, 40) || "(assistant only)"}`, {
        user_text: ellipsize(user),
        assistant_text: ellipsize(assistant),
        tool_calls_log: toolLog,
        project: projectSlug || null,
      }),
    ]);
  }

  pi.on(
    "before_agent_start",
    async (event: any, ctx: any) => {
      const setStatus = (text: string) => ctx?.ui?.setStatus?.("nous", text);
      try {
        if (!config.recall?.enabled || !config.apiKey) return;
        if (event?.messageType !== "user") return; // custom 起点の run には差し込まない
        const prompt = String(event.prompt ?? "").replace(/\s+/g, " ").trim();
        if (!prompt) return;
        const query = buildRecallQuery(prompt, projectSlug);
        if (!query) return;
        const started = Date.now();
        const payload = await fetchRecall(ellipsize(query, MAX_QUERY), config.recall.topK, projectSlug);
        const hits = parseRecallPayload(payload, config.recall.minScore, config.recall.topK);
        const wikiHits = parseWikiPayload(payload, WIKI_TOP_K);
        const ms = Date.now() - started;
        if (hits.length === 0 && wikiHits.length === 0) {
          setStatus(`nous recall: none · ${ms}ms`);
          return;
        }
        post([
          makeEvent(
            "recall.injected",
            `recall: ${hits.length} memories + ${wikiHits.length} wiki for "${ellipsize(query, 60)}"`,
            {
              query: ellipsize(query, MAX_QUERY),
              hits: hits.length,
              wiki_hits: wikiHits.length,
              wiki_slugs: wikiHits.map((w) => w.slug),
              project: projectSlug || null,
              min_score: config.recall.minScore,
              ms,
            },
          ),
        ]);
        console.error(`[nous-events] recall: injected ${hits.length} memories + ${wikiHits.length} wiki (${ms}ms)`);
        setStatus(
          `nous recall: ${hits.length}💭 ${wikiHits.length}📚 · top ${(wikiHits[0]?.score ?? hits[0]?.score ?? 0).toFixed(2)} · ${ms}ms`,
        );
        return {
          message: {
            customType: "nous-recall",
            content: formatRecall(hits, wikiHits),
            display: false,
          },
        };
      } catch (err) {
        setStatus("nous recall: error");
        logFailure(`recall: ${err instanceof Error ? err.message : String(err)}`);
      }
    },
  );

  pi.on("session_start", (event: any, ctx: any) => {
    try {
      config = resolveConfig();
      if (!config.apiKey && !warnedNoKey) {
        warnedNoKey = true;
        logFailure("NOUS_PLUGIN_API_KEY / nous.json / .env に API key が無いため送信を無効化");
      }
      const manager = ctx?.sessionManager;
      const id = typeof manager?.getSessionId === "function" ? manager.getSessionId() : "";
      sessionId = typeof id === "string" && id ? id : randomUUID();
      userText = "";
      turnSeq = 0;
      lastFlushedTurn = -1;
      assistantTexts = [];
      tools = [];
      pendingTools.clear();

      const cwd = typeof manager?.getCwd === "function" ? manager.getCwd() : "";
      projectSlug = resolveProject(String(cwd || ""));
      const name = typeof manager?.getSessionName === "function" ? manager.getSessionName() : undefined;
      post([
        makeEvent("session.started", `session started: ${ellipsize(String(cwd || "?"), 80)}`, {
          cwd,
          project: projectSlug || null,
          reason: event?.reason ?? null,
          name: name ?? null,
        }),
      ]);
    } catch (err) {
      logFailure(`session_start: ${err instanceof Error ? err.message : String(err)}`);
    }
  });

  pi.on("message_end", (event: any) => {
    try {
      const message = event?.message;
      if (!message) return;
      if (message.role === "user") {
        const text = textOf(message);
        if (text) {
          // 次のユーザーターン開始（assistant/tool ログもここで切替）
          userText = text;
          turnSeq += 1;
          assistantTexts = [];
          tools = [];
        }
      } else if (message.role === "assistant") {
        const text = textOf(message);
        if (text) {
          assistantTexts.push(text);
          if (assistantTexts.length > MAX_TOOL_LOG) assistantTexts = assistantTexts.slice(-MAX_TOOL_LOG);
        }
      }
    } catch (err) {
      logFailure(`message_end: ${err instanceof Error ? err.message : String(err)}`);
    }
  });

  pi.on("tool_execution_start", (event: any) => {
    try {
      pendingTools.set(event.toolCallId, {
        tool: String(event.toolName ?? ""),
        args_summary: argsSummary(event.args),
      });
    } catch {
      // 記録対象を落としても本処理は続行
    }
  });

  pi.on("tool_execution_end", (event: any) => {
    try {
      const pending = pendingTools.get(event.toolCallId);
      pendingTools.delete(event.toolCallId);
      if (tools.length >= MAX_TOOL_LOG) return;
      tools.push({
        tool: pending ? pending.tool : String(event.toolName ?? ""),
        args_summary: pending ? pending.args_summary : "",
        ok: !event.isError,
        ms: typeof event.durationMs === "number" ? event.durationMs : null,
      });
    } catch {
      // 1 件落としてもセッションは止めない
    }
  });

  pi.on("agent_before_settle", () => {
    try {
      flushTurn();
    } catch (err) {
      logFailure(`settle: ${err instanceof Error ? err.message : String(err)}`);
    }
  });

  pi.on("session_before_compact", (event: any) => {
    try {
      flushTurn(); // セーフネット: summary で文脈が消える前に送っておく
      const prep = event?.preparation;
      post([
        makeEvent("session.compacting", `compacting: ${ellipsize(String(event?.reason ?? "unknown"), 40)}`, {
          reason: event?.reason ?? null,
          willRetry: event?.willRetry ?? null,
          tokens_before: typeof prep?.tokensBefore === "number" ? prep.tokensBefore : null,
        }),
      ]);
    } catch (err) {
      logFailure(`compact: ${err instanceof Error ? err.message : String(err)}`);
    }
  });

  pi.on("session_shutdown", async (event: any) => {
    try {
      flushTurn();
      post([
        makeEvent("session.stopped", `session stopped: ${ellipsize(String(event?.reason ?? "quit"), 40)}`, {
          reason: event?.reason ?? null,
        }),
      ]);
      // shutdown はプロセス終了前に送り切る必要があるため、in-flight を有界で待つ
      // （個々の fetch は AbortSignal.timeout(TIMEOUT_MS) で有界。失敗は各 task 内で握る）
      await Promise.allSettled([...inflight]);
    } catch (err) {
      logFailure(`shutdown: ${err instanceof Error ? err.message : String(err)}`);
    }
  });
}
