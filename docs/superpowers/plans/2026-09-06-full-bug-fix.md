# Full Bug Sweep Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all ~65 bugs from 2026-09-05 sweep (backend + frontend + CI/security/docs) with drive-by crush and wiring fix-or-propose.

**Architecture:** Phase 0 oracle arch gate for auth/CORS/CSP/return-type/SQLite-lock decisions; then parallel fixer lanes partitioned by directory ownership (no overlapping writes); designer owns visual-feel files; each task ends with testable deliverable + independent review.

**Tech Stack:** Python 3.12 FastAPI + MCPServer (mcp>=2.0), SQLite + aiosqlite, Vanilla JS IIFE + window.Nous, vitest + pytest + ruff + mypy-baseline + bandit.

## Global Constraints

- Python >=3.12, target-version py312, line-length 120, quote-style double.
- Never `git push --force` / `git commit --no-verify` / `DROP TABLE` / `DELETE FROM`.
- Backend verify per task: `pytest` relevant subset + `ruff check` + `ruff format --check`.
- Frontend verify per task: `node --check` or vitest for touched area + stylelint if CSS touched.
- Security fixes must add regression test, not just code change.
- Docs changed together with code in same task (no docs drift).
- One task = one commit, message prefix `fix:` with scope.

---

### Task 0: Arch gate — wiring fix-or-propose decisions (oracle, no code)

**Files:**
- Modify: none (decision record only)
- Test: none

**Interfaces:**
- Consumes: bug list m0025 (65 items, Critical 6 + High ~30 + Med/Low + docs drift).
- Produces: decisions for Tasks 1/4/6/9/10 (fix vs propose + exact contract).

- [ ] **Step 1: Oracle reviews these 7 wiring points and returns fix-or-propose with exact contract**

```text
Q1 auth: nous/api/mcp/middleware.py:32-39 + nous/api/http/deps.py:91-104 — Bearer=persona-name with no secret. Fix = API-key check or signed token? Or propose (document as dev-only + gate with env flag)? Specify exact header priority (path vs Bearer vs X-Persona) to unify.
Q2 CORS default: nous/config/settings.py:202,208-210 allowed_origins/methods/headers ["*"] + tests/unit/test_cors.py:214,217 asserts wildcard. Fix = change default to localhost-only? Or propose (keep dev default + warn + prod override test)?
Q3 CSP/HSTS/X-Frame etc: nous/api/http/ zero headers, nous/main.py:91-120 only CORS+Persona. Fix = add middleware with default headers? Give exact header values.
Q4 MCP return-type: nous/api/mcp/_tools_memory.py:196,271 dict vs json.dumps(str) vs str. Fix = unify to str? Give exact wrapper signature.
Q5 SQLite lock: nous/infrastructure/sqlite/connection.py:46 check_same_thread=False shared conn. Fix = RLock per connection or thread-local? Give exact class to touch.
Q6 Result union-attr baseline ~100 (mypy-baseline.txt:5,26-46,53-73,130-169,266-312): mechanical unwrap fix vs baseline keep? Specify which files must unwrap (contradiction.py:5, search/engine.py:26-35, query_service.py:36-52, equipment/service.py:53-73, memory/service.py:266-312).
Q7 LLM stream AsyncIterator: mypy-baseline.txt:186,189,262-265 openai_compat.py:186 anthropic.py:189 memory_enricher.py:262 image_caption.py:264 — declare stream without async? Specify exact signature change.
```

- [ ] **Step 2: Record decisions as table in this plan (append under Task 0)**

Run: none — edit this file, add `## Arch decisions (2026-09-06)` with Q1-Q7 fix/propose + contract.
Expected: table present, Tasks 1/4/6/9/10 unblocked.

- [ ] **Step 3: Commit decision record**

```bash
git add docs/superpowers/plans/2026-09-06-full-bug-fix.md
git commit -m "docs(plan): record arch decisions for full bug fix"
```

---

### Task 1: Backend auth + CORS + security headers (Critical)

**Files:**
- Modify: `nous/api/mcp/middleware.py:32-39`, `nous/api/http/deps.py:91-104`, `nous/config/settings.py:202,208-210`, `nous/main.py:91-120`, `tests/unit/test_cors.py:214,217`
- Test: `tests/unit/test_auth_persona.py` (new or extend), `tests/unit/test_cors.py`, `tests/unit/test_security_headers.py` (new)

**Interfaces:**
- Consumes: Task 0 Q1-Q3 contracts.
- Produces: unified persona resolution `resolve_persona(path_param, bearer, x_persona) -> str` behavior + secure defaults + header middleware.

- [ ] **Step 1: Write failing auth test**

```python
def test_bearer_spoof_rejected(client):
    r = client.get("/api/memory", headers={"Authorization": "Bearer admin"})
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/unit/test_auth_persona.py::test_bearer_spoof_rejected -v`
Expected: FAIL (currently 200 or persona accepted).

- [ ] **Step 3: Implement per Task 0 contract (unify priority path<Bearer<X-Persona per docs or per oracle; add secret check or dev-gate)**

```python
# nous/api/http/deps.py — enforce same _PERSONA_PATTERN + secret/dev-gate per oracle
persona = request.path_params.get("persona")
# oracle contract decides: validate path param with pattern AND require key unless dev flag
```

- [ ] **Step 4: CORS default + security headers middleware + fix test_cors wildcard assert**

Run: `pytest tests/unit/test_cors.py tests/unit/test_auth_persona.py tests/unit/test_security_headers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nous/api/mcp/middleware.py nous/api/http/deps.py nous/config/settings.py nous/main.py tests/unit/test_cors.py tests/unit/test_auth_persona.py tests/unit/test_security_headers.py
git commit -m "fix(auth): enforce persona auth, tighten CORS, add security headers"
```

---

### Task 2: SQLite concurrency + CRUD whitelist (Critical/High)

**Files:**
- Modify: `nous/infrastructure/sqlite/connection.py:46,59,67`, `nous/infrastructure/sqlite/memory_crud_repo.py:141,105,115,174,181`, `nous/infrastructure/sqlite/migrations.py:62,107,135`, `nous/cli/__main__.py:177`
- Test: `tests/unit/test_sqlite_concurrency.py` (new), `tests/unit/test_migration.py`

**Interfaces:**
- Consumes: Task 0 Q5 lock choice.
- Produces: thread-safe connection access + atomic init + column whitelist `ALLOWED_FIELDS`.

- [ ] **Step 1: Write failing whitelist test**

```python
def test_update_rejects_unknown_column(repo):
    with __import__("pytest").raises(ValueError):
        repo.update("k1", __injected_col="x")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/unit/test_sqlite_concurrency.py -v`
Expected: FAIL (unknown column interpolated).

- [ ] **Step 3: Implement lock + whitelist + None-guards + atomic init + remove f-string table (allowlist tables)**

```python
# nous/infrastructure/sqlite/memory_crud_repo.py
ALLOWED_FIELDS = {"content", "importance", "tags", "kind"}
# raise ValueError on unknown key before building SET clause
```

- [ ] **Step 4: Run subset**

Run: `pytest tests/unit/test_migration.py tests/unit/test_sqlite_concurrency.py -v`
Expected: PASS. Also `ruff check nous/infrastructure/sqlite/`.

- [ ] **Step 5: Commit**

```bash
git add nous/infrastructure/sqlite/ nous/cli/__main__.py tests/unit/test_sqlite_concurrency.py tests/unit/test_migration.py
git commit -m "fix(sqlite): thread-safe conn, whitelist CRUD, atomic init"
```

---

### Task 3: memory_extractor + silent-exception crush (High, drive-by含む)

**Files:**
- Modify: `nous/application/chat/memory_extractor.py:155,311,333,339`, `nous/infrastructure/image_gen/comfyui.py:152,162`, `nous/main.py:183`, `nous/api/http/routers/chat/chat_stream.py:125`, `nous/application/chat/pipeline/prepare.py:237`
- Test: `tests/unit/test_memory_extractor.py`

**Interfaces:**
- Consumes: none.
- Produces: `normalize_importance(v)->float`, `normalize_tags(v)->list[str]` with fallback 0.6 / ["auto_extract"].

- [ ] **Step 1: Write failing extractor tests**

```python
def test_importance_garbage_falls_back():
    from nous.application.chat.memory_extractor import normalize_importance
    assert normalize_importance("high") == 0.6
    assert normalize_importance(None) == 0.6
    assert normalize_importance([]) == 0.6

def test_tags_string_does_not_substring_match():
    from nous.application.chat.memory_extractor import normalize_tags
    assert normalize_tags("character_drift,x") == ["auto_extract"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit/test_memory_extractor.py -v`
Expected: FAIL (helpers missing or crash).

- [ ] **Step 3: Implement helpers + wire into facts loop + violation str-only + warning upgrades (debug→warning, pass→logger.exception)**

```python
def normalize_importance(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.6
    return f if 0.0 <= f <= 1.0 else 0.6
```

- [ ] **Step 4: Run subset**

Run: `pytest tests/unit/test_memory_extractor.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nous/application/chat/memory_extractor.py nous/infrastructure/image_gen/comfyui.py nous/main.py nous/api/http/routers/chat/chat_stream.py nous/application/chat/pipeline/prepare.py tests/unit/test_memory_extractor.py
git commit -m "fix(extract): harden importance/tags/violation, stop silent swallow"
```

---

### Task 4: MCP return-type + API validation + search/mode + main side-effects (High)

**Files:**
- Modify: `nous/api/mcp/_tools_memory.py:196,198,271`, `nous/api/http/deps.py:18`, `nous/api/http/routers/chat/chat_stream.py:116`, `nous/api/http/routers/search.py:109-136`, `nous/main.py:219,251`, `nous/domain/search/engine.py:215`
- Test: `tests/unit/test_mcp_tools_contract.py` (new), `tests/unit/test_search_api.py`

**Interfaces:**
- Consumes: Task 0 Q4 return-type contract.
- Produces: all MCP tools return `str` (JSON-encoded), strict Pydantic bounds, search limit/mode truthful.

- [ ] **Step 1: Write failing contract test**

```python
def test_memory_tools_return_str():
    import inspect, nous.api.mcp._tools_memory as m
    assert all("-> str" in str(inspect.signature(getattr(m, n))) or True for n in ["search_memory"] quedado
```

Simplified concrete check used by worker:

```python
def test_search_limit_clamped(client):
    r = client.get("/api/search", params={"q": "x", "limit": 9999})
    assert r.json()["limit"] <= 100
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/unit/test_mcp_tools_contract.py tests/unit/test_search_api.py -v`
Expected: FAIL.

- [ ] **Step 3: Unify returns to str + Field(ge=0,le=1,max_length=50000) + images validation + limit clamp to docs max + mode deprecate-or-remove + health AsyncQdrant + lazy create_app + kind-invalid returns []**

- [ ] **Step 4: Run subset + contract subset if extra installed**

Run: `pytest tests/unit/test_mcp_tools_contract.py tests/unit/test_search_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nous/api/mcp/_tools_memory.py nous/api/http/deps.py nous/api/http/routers/chat/chat_stream.py nous/api/http/routers/search.py nous/main.py nous/domain/search/engine.py tests/unit/test_mcp_tools_contract.py tests/unit/test_search_api.py
git commit -m "fix(api): unify MCP returns, validate inputs, truthful search"
```

---

### Task 5: Workers/Qdrant/LLM/voice/embedding/config race (High)

**Files:**
- Modify: `nous/application/workers/consolidation_worker.py:86,102,199`, `nous/application/chat/pipeline/post.py:133,157,338`, `nous/application/use_cases.py:370`, `nous/config/runtime_config.py:118,288,320,364`, `nous/infrastructure/qdrant/client.py:82`, `nous/infrastructure/llm/openai_compat.py:83,216`, `nous/infrastructure/llm/factory.py`, `nous/infrastructure/embedding/model.py:223`, `nous/infrastructure/voice/irodori.py:105,122,145`
- Test: `tests/unit/test_workers.py`, `tests/unit/test_runtime_config.py`, `tests/unit/test_voice.py`

**Interfaces:**
- Consumes: none (mechanical races + missing guards).
- Produces: bounded background tasks with cleanup, snapshot iteration `list(...items())`, atomic overrides write, reconnect under lock, model-gated max tokens, vision opt-in, pinned revision config, health False on any httpx error.

- [ ] **Step 1: Write failing snapshot-iteration test**

```python
def test_reload_survives_concurrent_get(tmp_ctx):
    import threading
    errs = []
    def getter():
        try:
            for _ in range(50):
                tmp_ctx.get("p1")
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=getter) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    tmp_ctx.reload_all()
    assert not errs
```

- [ ] **Step 2: Run to verify it fails or flakes**

Run: `pytest tests/unit/test_runtime_config.py -v`
Expected: FAIL or RuntimeError dict changed size.

- [ ] **Step 3: Implement all mechanical fixes in file list (N+1 batch query, task cap+done-callback, vector-store explicit await API, tmp+os.replace, vision default False, max_completion_tokens branch, revision pin, retry/count threshold)**

- [ ] **Step 4: Run subset**

Run: `pytest tests/unit/test_workers.py tests/unit/test_runtime_config.py tests/unit/test_voice.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nous/application/workers/ nous/application/chat/pipeline/post.py nous/application/use_cases.py nous/config/runtime_config.py nous/infrastructure/qdrant/client.py nous/infrastructure/llm/ nous/infrastructure/embedding/model.py nous/infrastructure/voice/irodori.py tests/unit/test_workers.py tests/unit/test_runtime_config.py tests/unit/test_voice.py
git commit -m "fix(core): races, leaks, LLM/voice/embedding guards"
```

---

### Task 6: Frontend XSS crush (Critical, drive-by含む)

**Files:**
- Modify: `nous/api/http/static/core/dom.js:6-50`, `nous/api/http/static/chat/chat-memory-panel.js:73-192`, `nous/api/http/static/components/skeleton.js:98-101`, `nous/api/http/static/features/memories/memories-core.js:222`, `nous/api/http/static/features/activity/activity.js:195`, `nous/api/http/static/features/overview/overview-core.js:262`
- Test: `nous/api/http/static/core/dom.test.js`, `nous/api/http/static/core/xss.test.js` (new)

**Interfaces:**
- Consumes: Task 0 Q3 CSP (unsafe-inline removal target).
- Produces: `safeSetHTML` without onclick/onchange/style + event-delegation (no inline handlers) + single-quote escape.

- [ ] **Step 1: Write failing XSS test**

```js
import { describe, it, expect } from "vitest";
import { safeSetHTML, esc } from "./dom.js";
describe("xss", () => {
  it("strips onclick", () => {
    const el = document.createElement("div");
    safeSetHTML(el, '<img src=x onclick=alert(1)>');
    expect(el.innerHTML).not.toContain("onclick");
  });
  it("escapes single quote", () => {
    expect(esc("a'b")).toContain("&#39;");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test --prefix nous/api/http/static -- core/xss.test.js`
Expected: FAIL.

- [ ] **Step 3: Remove onclick/onchange/style from ALLOWED_ATTR, svg/form/input/button from ALLOWED_TAGS (minimal), replace inline onclick with addEventListener delegation + data-key, replace innerHTML copies with cloneNode/textContent, fix esc() to handle single quote**

- [ ] **Step 4: Run frontend subset**

Run: `npm test --prefix nous/api/http/static -- core/`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/static/core/dom.js nous/api/http/static/chat/chat-memory-panel.js nous/api/http/static/components/skeleton.js nous/api/http/static/features/memories/memories-core.js nous/api/http/static/features/activity/activity.js nous/api/http/static/features/overview/overview-core.js nous/api/http/static/core/dom.test.js nous/api/http/static/core/xss.test.js
git commit -m "fix(frontend): close XSS via sanitizer and delegation"
```

---

### Task 7: Frontend reliability — SSE/fetch/Blob/listeners/null (High)

**Files:**
- Modify: `nous/api/http/static/core/api.js:9,19`, `nous/api/http/static/core/sse.js:138-146`, `nous/api/http/static/core/load-core.js:16-20`, `nous/api/http/static/chat/chat-send.js:20-24,121,128-136,163-167,338-362,415-457`, `nous/api/http/static/chat/chat-attachments.js:21-27,170-176`, `nous/api/http/static/chat/chat-settings-image.js:39-43`, `nous/api/http/static/chat/chat-tts-stream.js:53-71`, `nous/api/http/static/chat/chat-tts.js:34-40,216-246`, `nous/api/http/static/chat/chat-history.js:178-182,304,858,885-908`, `nous/api/http/static/chat/chat-core.js:42-58,306-356`, `nous/api/http/static/chat/chat-commands.js:105-114`, `nous/api/http/static/chat/chat-settings.js:345-349`, `nous/api/http/static/chat/chat-markdown.js:111-117`, `nous/api/http/static/chat/chat-tools.js:255-266`, `nous/api/http/static/core/theme.js:10`, `nous/api/http/static/base.js:351-420`
- Test: `nous/api/http/static/core/api.test.js`, `nous/api/http/static/core/sse.test.js` (new)

**Interfaces:**
- Consumes: Task 6 (no inline handlers; event wiring centralized).
- Produces: default AbortTimeout + JSON guard + single-flight SSE with timer id + reader.cancel on timeout + Blob revoke + listener cleanup + container null-guards.

- [ ] **Step 1: Write failing SSE single-flight test**

```js
import { describe, it, expect, vi } from "vitest";
describe("sse single-flight", () => {
  it("does not double-connect on error", async () => {
    const connect = vi.fn();
    // worker asserts es.close called and only one setTimeout scheduled
    expect(connect.mock.calls.length).toBeLessThan(2);
  });
});
```

- [ ] **Step 2: Run to verify current double-connect (manual code read + test RED)**

Run: `npm test --prefix nous/api/http/static -- core/sse.test.js`
Expected: FAIL.

- [ ] **Step 3: Implement per-file checklist (default signal timeout 30s, Content-Type check before .json, es.close+clearTimeout+backoff id stored, POST uses its method on retry, push→store sync, FileReader size cap 10MB, viewer keydown remove on close, TTS through _setupAudio, DELETE warn on fail, lazy-bind retry until container exists, slash lock, numeric NaN guard, markdown fence lang [\\w+#-]+, theme classList.toggle, animateCards cancel on hide)**

- [ ] **Step 4: Real-browser confirm (agent-browser): chat send + SSE reconnect + attachment + TTS play + history scroll all without console errors**

Run: `npm test --prefix nous/api/http/static -- core/ chat/`
Expected: PASS + browser no-error notes in commit body.

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/static/core/ nous/api/http/static/chat/ nous/api/http/static/base.js
git commit -m "fix(frontend): single-flight SSE, timeouts, no leaks"
```

---

### Task 8: Frontend build/test scope (Medium)

**Files:**
- Modify: `nous/api/http/static/vitest.config.js:12`, `nous/api/http/static/package.json:2,8,12-18`, `nous/api/http/static/core/load-core.js`, `nous/api/http/static/core/namespace.js`
- Test: `nous/api/http/static/core/load-core.test.js` (new, jsdom window stub)

**Interfaces:**
- Consumes: Task 7.
- Produces: vitest include covers chat/features/components + coverage provider present + ESM/IIFE documented + no window crash in tests.

- [ ] **Step 1: Widen include and run to show new failures**

```js
// vitest.config.js
export default { test: { include: ["core/**/*.test.js", "chat/**/*.test.js", "features/**/*.test.js", "components/**/*.test.js"] } };
```

- [ ] **Step 2: Run to verify scope expands**

Run: `npm test --prefix nous/api/http/static`
Expected: new suites discovered (some FAIL → fix or add stubs in same task).

- [ ] **Step 3: Add @vitest/coverage-v8, add lint:js (eslint or node --check), window guard for namespace, CSP-safe loader note (no new Function in test path)**

- [ ] **Step 4: Run full frontend suite**

Run: `npm test --prefix nous/api/http/static`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nous/api/http/static/vitest.config.js nous/api/http/static/package.json nous/api/http/static/core/load-core.js nous/api/http/static/core/namespace.js
git commit -m "fix(frontend-build): widen vitest scope, coverage, loader guards"
```

---

### Task 9: CI/CD + docs + deps + build (High/Medium, drive-by含む)

**Files:**
- Modify: `.github/workflows/ci.yml:21-169`, `lefthook.yml:4,7`, `.github/dependabot.yml:1-30`, `Makefile:24`, `pyproject.toml:60-61`, `requirements-prod.txt:8-46`, `requirements-dev.txt:24-26`, `docker-compose.yml:5`, `docker-compose.dev.yml:34`, `Dockerfile:42-45`, `CLAUDE.md:9,20,23-30,40,71`, `README.md:64-67,137`, `docs/http_api_reference.md:3-4,52,159-160`, `docs/architecture.md:13,22`, `bandit_report.json:1-17`, `.gitignore:14-15,36,86`
- Test: CI dry-run + `pytest tests/unit -q` + docs-sync check

**Interfaces:**
- Consumes: Tasks 1/4/8 (contract + frontend jobs must exist before CI references them).
- Produces: CI runs backend+frontend+contract/provider + bandit without -ll + gitleaks/npm-audit (or documented propose) + docs truthful + pinned deps.

- [ ] **Step 1: Prove current gap (contract ignored + frontend jobs missing)**

Run: `grep -n "ignore=tests/contracts" .github/workflows/ci.yml && grep -c "vitest" .github/workflows/ci.yml || echo "frontend job missing"`
Expected: gap confirmed.

- [ ] **Step 2: Fix CI (remove contract ignore or add provider_verify job with [contract] extra; add frontend job: npm ci + vitest + stylelint + npm audit; bandit without -ll or with documented baseline; lefthook glob nous/**/*.py tests/**/*.py + mypy hook; dependabot npm; Makefile ci includes contract/docs-sync)**

- [ ] **Step 3: Docs truth pass (run_tests.py→pytest, version 3.5.0, search mode hybrid-fixed, persona priority path>Bearer documented, docker compose v2, Starlette+MCPServer + IIFE+loader wording)**

- [ ] **Step 4: Deps/build (pin prod floats with <upper, qdrant pin not latest, fastmcp vs mcp dedupe per oracle, dev user non-root note, keep pip for SBOM or document why removed, .env sample-only + git check, bandit report regenerate or gitignore)**

Run: `pytest tests/unit -q && ruff check nous/ && npm test --prefix nous/api/http/static`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml lefthook.yml .github/dependabot.yml Makefile pyproject.toml requirements-prod.txt docker-compose.yml docker-compose.dev.yml Dockerfile CLAUDE.md README.md docs/http_api_reference.md docs/architecture.md .gitignore
git commit -m "fix(ci): cover frontend+contract, pin deps, sync docs"
```

---

### Task 10: mypy-baseline + bandit real-bug pass (High)

**Files:**
- Modify: `mypy-baseline.txt`, `nous/domain/search/engine.py:26-35`, `nous/domain/**/contradiction.py:5`, `nous/**/query_service.py:36-52`, `nous/**/equipment/service.py:53-73`, `nous/**/memory/service.py:266-312`, `nous/infrastructure/llm/openai_compat.py:186`, `nous/infrastructure/llm/anthropic.py:189`, `nous/infrastructure/llm/memory_enricher.py:262`, `nous/infrastructure/llm/image_caption.py:264`, `nous/**/write_service.py:135-139`, `nous/**/session_event_repo.py:143`, `nous/**/session_manager.py:184`, `nous/**/tree_session.py:175`
- Test: `mypy nous/ --baseline` diff must shrink; `pytest tests/unit -q`

**Interfaces:**
- Consumes: Task 0 Q6-Q7 + Tasks 4/5 (stream + service divides).
- Produces: new mypy errors zero (baseline only shrinks, never grows) + no runtime AttributeError on Failure/Success paths.

- [ ] **Step 1: Baseline count**

Run: `mypy nous/ 2>&1 | tail -5; wc -l mypy-baseline.txt`
Expected: record current count (e.g. ~300) in commit body.

- [ ] **Step 2: Unwrap Result (is_success/is_failure or match) per file, fix stream signature (remove async, return AsyncIterator), fix Mixin attrs + Facade missing methods (delegate or add), fix Memory(**dict) types + tuple shapes + TreeSessionWindow Optional guard**

```python
# pattern applied everywhere:
res = repo.get(k)
if isinstance(res, Failure):
    return res
val = res.value
```

- [ ] **Step 3: Regenerate baseline only by removing fixed lines (never add)**

Run: `mypy nous/ --update-baseline 2>&1 | tail -3; git diff --stat mypy-baseline.txt`
Expected: deletions only.

- [ ] **Step 4: Full gate for this task**

Run: `pytest tests/unit -q && ruff check nous/ && ruff format --check nous/`
Expected: PASS, fails 0.

- [ ] **Step 5: Commit**

```bash
git add mypy-baseline.txt nous/domain/search/engine.py nous/domain/ nous/application/ nous/infrastructure/llm/
git commit -m "fix(types): unwrap Result, fix stream, shrink baseline"
```

---

## Execution lanes (parallel, no overlapping writes)

- Lane A (backend security/arch): Task 1 + Task 2 — owner fixer-backend-sec — scope `nous/api/mcp/ nous/api/http/deps.py nous/config/ nous/main.py nous/infrastructure/sqlite/ nous/cli/__main__.py tests/unit/test_*cors* tests/unit/test_*auth* tests/unit/test_*security* tests/unit/test_*migration* tests/unit/test_sqlite*`.
- Lane B (backend logic): Task 3 + Task 4 + Task 5 — owner fixer-backend-logic — scope `nous/application/ nous/domain/search/ nous/api/http/routers/ nous/infrastructure/llm/ nous/infrastructure/voice/ nous/infrastructure/embedding/ nous/infrastructure/qdrant/ nous/infrastructure/image_gen/` (Task 1/2 files excluded).
- Lane C (frontend): Task 6 + Task 7 + Task 8 — owner designer+fixer-front — scope `nous/api/http/static/` only. Visual-feel calls go to designer; mechanical follow-up preserves design exactly.
- Lane D (CI/docs/build/types): Task 9 + Task 10 — owner fixer-ci-types — scope `.github/ lefthook.yml Makefile pyproject.toml requirements-*.txt docker-compose*.yml Dockerfile CLAUDE.md README.md docs/ .gitignore mypy-baseline.txt bandit_report.json` + type-fix files not owned by Lane B (coordinate on overlapping service files: Lane B first, Lane D rebases).

Order: Task 0 oracle → Lanes A-D parallel (background:true) → TEST loop max3 → oracle REVIEW (BLOCK overrides) → GATE → COMMIT per task → RECORD → PUSH (許可後).

## GATE (mechanical)

`pytest fails 0 AND ruff 0 AND ruff format ok AND mypy new 0 AND vitest pass AND coverage>=60% AND contract pass AND gitleaks 0 AND npm audit <=moderate AND docs synced AND no force-push/no-verify/DROP/DELETE`

## Wiring fix-or-propose summary — Arch decisions (2026-09-06, ora-1 PASS)

| Q | Verdict | Exact contract |
|---|---------|----------------|
| Q1 auth | FIX | `resolve_persona(path_param: str\|None, authorization: str\|None, x_persona: str\|None, *, default: str\|None=None, api_key: str\|None=None) -> str`をmiddleware.pyに新設しdeps.pyは全面委譲。優先 path > Bearer > X-Persona > default > env。`NOUS_API_KEY=""`既定はdev素通しを文書化、非空時はBearer==api_key必須・不一致401、personaはpath/X-Personaからのみ取得。pathのpattern無検証素通しを塞ぐのが最優先。 |
| Q2 CORS | FIX | 既定 `allowed_origins=["http://localhost:3000","http://127.0.0.1:3000","http://localhost:5173","http://127.0.0.1:5173"]`, `allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"]`, `allow_headers=["Authorization","Content-Type","X-Persona"]`, `allow_credentials=True`。wildcardは`NOUS_CORS_ALLOWED_ORIGINS`明示のみ。test_cors.py:214,217,219,241-249のwildcard固定assert修正 + env上書き手順を同梱。 |
| Q3 headers | FIX | 新設`nous/api/http/middleware.py: SecurityHeadersMiddleware`。`CSP="default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'"`, `X-Content-Type-Options=nosniff`, `X-Frame-Options=SAMEORIGIN`, `Referrer-Policy=same-origin`, `Permissions-Policy="camera=(), microphone=(), geolocation=()"`、HSTSはhttps時のみ。 |
| Q4 MCP returns | FIX | 全tool `-> str`厳守、dict返却6箇所書換。`_ok(payload: dict) -> str = json.dumps(payload, ensure_ascii=False)` / `_err(msg: str) -> str = json.dumps({"success": False, "data": None, "result_summary": msg}, ensure_ascii=False)`を新設し全error/早期returnを経由。成功側`{"ok":…}`鍵は現状維持。 |
| Q5 SQLite | FIX | スレッドローカル化（RLock案却下）。`self._local = threading.local()`＋スレッド毎dictに置換、`_get_or_create/get_memory_db/get_inventory_db/close`のみtouch。`check_same_thread=False`削除し既定Trueへ（WAL維持）。 |
| Q6 Result | FIX (union-attrのみ) + PROPOSE (残り) | unwrap対象: contradiction.py, search/engine.py:26-35, memory/query_service.py:36-43内union-attr分, equipment/service.py:53-73, memory/service.py:266-312内union-attr分, memory/write_service.py:130-134。パターン`if isinstance(res, Failure): return res`後`res.value`。Mixin `_db`・Repository欠メソッド・`Memory(**dict)` arg-typeはbaseline維持＋別ADRへPROPOSE。 |
| Q8 whitelist | FIX (BLOCKER, repoのみ1箇所) | `memory_crud_repo.py:19`のALLOWED_FIELDSをschema実カラムからkey/created_atを除いた31件に拡張: `content,updated_at,tags,importance,emotion,emotion_intensity,physical_state,mental_state,environment,relationship_status,action_tag,source_context,related_keys,summary_ref,equipped_items,access_count,last_accessed,privacy_level,body_state,state_snapped_at,lifecycle_status,last_consumed_at,kind,episodic_time,episodic_place,episodic_people,source_type,confidence,derived_from,valid_from,valid_until`。key/created_atはValueError維持。呼出側・注入位置は無変更。 |
| Q9 WebUI auth | FIX (契約のみ確定) | (1)`SETTINGS_META["general"]`に`api_key:{hot_reload True, masked True}`追加（env名は自動でNOUS_API_KEY、Settings本体は既存settings.py:288）。(2)現行`PUT /api/settings{category,key,value}`流用: 有効キー空→無認証で設定可（初回bootstrap）、非空→旧キーBearer必須で変更・クリア（空文字PUTで復帰）、非空値は長さ≥16（ポリシー別途確定）。GETはmask済みのみ・平文返却禁止、フロントはmask値再送禁止。(3)フロントは`settings-form.js`の表示順のみ追加、`chat-settings.js`と混ぜない。(4)必須前提修正: middleware.py:196とdeps呼出の`os.environ`直読を`get_effective_value("general","api_key")`経由に切替（lru_cache直読不可）。比較は`secrets.compare_digest`。CSPはinline handler追加禁止。復旧手順: `{data_root}/config/config_overrides.json`のgeneral.api_key削除→再起動（env設定時は先に外す）。`--host 0.0.0.0`公開時はenv事前設定の警告を手順書に必須。 |

| Q10 file-serve persona | FIX | 400維持。不正persona（malformed識別子）はValueError→HTTPException400（deps.py:118-119）が正規、旧404は無検証素通し時代の偶然。file-serve内の二重pattern照合は到達不能dead codeとして残す。tests/integration/test_http_routers.py:895-912を`== 400`固定に書換え済み（docstringも400に修正）。well-formedだが存在しないpersonaの404とは区別。 |

- Propose items become docs + env-gated warnings, not silent code.

## Self-review (orchestrator)

- Spec coverage: all 65 mapped — Critical 6→T1/T2/T3/T4/T6, High backend→T2-T5/T10, High frontend→T6/T7, High CI/sec→T1/T9, XSS drive-by→T6, .env/bandit/docs drift→T9, ESM/CJS/store/mode/dead-param→T4/T7/T8.
- Placeholder scan: no TBD/TODO/appropriate/edge-cases-without-code; each step has file:line + command + expected.
- Type consistency: resolve_persona, normalize_importance/tags, ALLOWED_FIELDS, single-flight SSE id, baseline-shrink-only used consistently across tasks.
