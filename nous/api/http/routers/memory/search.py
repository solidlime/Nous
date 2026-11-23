from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import (
    _memory_to_dict,
    _resolve_persona_from_request,
    _safe_get_context,
)
from nous.api.http.routers._error_handlers import error_from_result
from nous.domain.search.engine import SearchQuery, final_rank_key
from nous.domain.shared.result import Success
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)

# decision クエリパラメータ（0/1/true/false）の真値集合（最小パース）。
_TRUTHY_VALUES = frozenset({"1", "true", "on", "yes"})

#: project タグ保持の記憶への相対ブースト。合成スコアは非正規化（実測 1.0-2.6 程度）なので
#: 加算ではなく乗算 1.25 倍。同点付近の並びを入れ替えるが、スコア差 25% を覆さない。
PROJECT_MEMORY_BOOST = 1.25


def apply_project_boost(rows: list[dict], project: str) -> list[dict]:
    """``project:<slug>`` タグ保持の行をブーストしてスコア降順に並べ直す。

    rows は ``{memory, score, source, time_weight}`` の辞書（``/api/search`` の応答単位）。
    ``memory.tags`` を見るのでドメイン型に依存しない。

    並べ替えキーは engine の最終順位と同じ ``score * time_weight`` を使う。
    engine は判定ゲート後のソートにだけ時間重みを掛けるので、ここで落とすと
    「project を付けただけで同クエリの順序が変わる」ことになる。
    ブーストが 1 件も当たらなければ engine の順序をそのまま返す。
    """
    if not project:
        return rows
    tag = f"project:{project}"
    boosted: list[dict] = []
    hit = False
    for row in rows:
        tags = (row.get("memory") or {}).get("tags") or []
        if isinstance(tags, list) and tag in tags:
            row = {**row, "score": round(float(row.get("score") or 0.0) * PROJECT_MEMORY_BOOST, 4)}
            hit = True
        boosted.append(row)
    if not hit:
        return rows
    return sorted(
        boosted,
        key=lambda r: final_rank_key(float(r.get("score") or 0.0), r.get("time_weight")),
        reverse=True,
    )


def _parse_decision_flag(value: str | None) -> bool:
    """decision query param を bool 化する（未知値は False）。"""
    return (value or "").strip().lower() in _TRUTHY_VALUES


def _entity_typed_by(row: dict) -> str | None:
    """Return ``entities.metadata.typed_by`` (the typing provenance) or None.

    The color map only paints an entity when its type came from a trusted
    typing path; entities written by the regex extractor have no ``typed_by``
    yet, so they stay unpainted (grey) until the LLM typist backfills them.
    """
    raw = row.get("metadata")
    if not raw:
        return None
    try:
        meta = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    typed_by = meta.get("typed_by")
    return typed_by if isinstance(typed_by, str) and typed_by else None


def _merge_entity_layer(ctx, memories: list, nodes: list, edges: list, edge_set: set) -> None:
    """Append entity nodes and mentions/relation edges to the graph (display-only superset).

    Repo contract (implemented on the repository side by Lane B):
        get_entities_for_memories(memory_keys, limit=50)
            -> [{id, label, type, mention_count, metadata, memory_key}]
        get_relations_between_entities(entity_ids)
            -> [{source_id, target_id, relation, confidence}]

    FYI(accepted): tags also surface as concept entities (see domain/memory/graph.py).
    enrichment 廃止（2026-11-08）で relation の書き手が無くなった。既存の
    entity_relations 行は凍結データとして描画のみ続ける（新規には増えない）。
    書き込み経路 (EntityService.add_relation) は削除済み（kanban #35）。
    """
    # getattr guard keeps the endpoint backward-compatible until Lane B lands.
    repo = getattr(ctx, "entity_repo", None)
    if repo is None:
        return
    get_entities = getattr(repo, "get_entities_for_memories", None)
    if get_entities is None:
        return
    try:
        rows = get_entities([m.key for m in memories], limit=50)
    except Exception:
        logger.warning("graph: entity fetch failed; serving memory-only graph", exc_info=True)
        return

    by_id: dict[str, dict] = {}
    for row in rows or []:
        eid = row.get("id")
        if not eid:
            continue
        cur = by_id.get(eid)
        if cur is None or (row.get("mention_count") or 0) > (cur.get("mention_count") or 0):
            by_id[eid] = row
    top = sorted(by_id.values(), key=lambda r: r.get("mention_count") or 0, reverse=True)[:50]
    visible = {r["id"] for r in top}

    for row in top:
        nodes.append(
            {
                "key": f"ent:{row['id']}",
                "kind": "entity",
                "label": row.get("label") or row["id"],
                "entity_type": row.get("type"),
                "typed_by": _entity_typed_by(row),
                "mention_count": row.get("mention_count", 0),
            }
        )

    for row in rows or []:
        source = row.get("memory_key") or ""
        target_id = row.get("id")
        if not source or target_id not in visible:
            continue  # sentinel rows and edges to capped-out entities are dropped
        marker = ("mentions", source, target_id)
        if marker not in edge_set:
            edge_set.add(marker)
            edges.append({"source": source, "target": f"ent:{target_id}", "type": "mentions"})

    get_relations = getattr(repo, "get_relations_between_entities", None)
    if get_relations is None:
        return
    try:
        relations = get_relations(sorted(visible))
    except Exception:
        logger.warning("graph: relation fetch failed; skipping relation edges", exc_info=True)
        return
    for rel in relations or []:
        sid, tid = rel.get("source_id"), rel.get("target_id")
        if sid not in visible or tid not in visible:
            continue  # relation edges require both endpoints visible
        marker = ("relation", sid, tid)
        if marker not in edge_set:
            edge_set.add(marker)
            edges.append(
                {
                    "source": f"ent:{sid}",
                    "target": f"ent:{tid}",
                    "type": "relation",
                    "relation": rel.get("relation"),
                    "confidence": rel.get("confidence"),
                }
            )


_BODY_METRICS = ("fatigue", "warmth", "arousal", "heart_rate", "pain")


def _state_digest(ctx, persona: str) -> dict | None:
    """現在の状態を 1 つの dict に畳む（pi 拡張が recall と一緒に注入する読み取り専用ビュー）。

    取得失敗は None。検索自体は落とさない。
    """
    try:
        result = ctx.persona_service.get_context(persona)
        if not isinstance(result, Success):
            return None
        state = result.value
        body: dict[str, float] = {}
        for key in _BODY_METRICS:
            value = getattr(state, key, None)
            # bool は isinstance(True, int) が真になるので明示的に落とす
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            body[key] = round(float(value), 3)
        return {
            "emotion": state.emotion,
            "emotion_intensity": state.emotion_intensity,
            "physical_state": state.physical_state,
            "mental_state": state.mental_state,
            "environment": state.environment,
            "relationship_status": state.relationship_status,
            "body": body,
            "user": dict(getattr(state, "user_info", None) or {}),
        }
    except Exception:
        logger.debug("state digest failed", exc_info=True)
        return None


def _load_chat_config(persona: str):
    """persona の ChatConfig。読み込み失敗はデフォルトに倒す（注入だけが欠ける）。"""
    from nous.config.settings import get_settings
    from nous.domain.config.chat_config import ChatConfig, ChatConfigFileRepository

    try:
        return ChatConfigFileRepository(get_settings().data_root).get(persona)
    except Exception:
        logger.warning("chat config load failed for '%s': using defaults", persona, exc_info=True)
        return ChatConfig(persona=persona)


async def _build_injection(ctx, persona: str, rows: list, wiki_hits: list, config) -> str:
    """チャットと同じ整形で注入ブロックを組み立てる（pi 拡張がそのまま載せる）。

    ``_passes_min_score`` は注入の記憶行にだけ適用する（``results[]`` は無フィルタ）。
    """
    from nous.application.chat.pipeline.context_loader import _build_context_section
    from nous.application.chat.pipeline.injection import build_injection_block, format_memory_lines, format_wiki_lines
    from nous.application.chat.pipeline.memory_retriever import _passes_min_score
    from nous.application.chat.pipeline.prepare import _build_time_context, state_to_raw

    min_score = getattr(config, "memory_min_score", None)
    memories, _ = format_memory_lines([r for r in rows if _passes_min_score(r, min_score)])

    state = None
    state_result = ctx.persona_service.get_context(persona)
    if isinstance(state_result, Success):
        state = state_result.value
    context_section = ""
    if state is not None:
        # 減衰は適用しない（GET で書き込み副作用を起こさない — chat との明示的な差）。
        context_section = await _build_context_section(
            ctx,
            state,
            None,
            compress_mode=getattr(config, "context_compression_mode", "auto"),
            emotion_bands=(
                getattr(config, "emotion_hint_low", 0.35),
                getattr(config, "emotion_hint_high", 0.7),
            ),
            config=config,
        )

    return build_injection_block(
        ctx,
        time_context=_build_time_context(state) if state is not None else "",
        state_raw=state_to_raw(state) if state is not None else {},
        context_section=context_section,
        memories=memories,
        wiki=format_wiki_lines(wiki_hits, k=2),
        config=config,
    )


def register_search_routes(mcp) -> None:
    @mcp.custom_route("/api/search/{persona}", methods=["GET"])
    async def search_memories(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        q = request.query_params.get("q", "")
        try:
            limit = int(request.query_params.get("limit", "20"))
        except ValueError:
            return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        if limit < 1:
            # 上限超過は黙って 100 にクランプするが、0/負は弾く（#89）
            return JSONResponse(
                {"error": "limit must be a positive integer (larger values are clamped to 100)"}, status_code=400
            )
        limit = min(limit, 100)
        mode = request.query_params.get("mode", "hybrid")
        date_range = request.query_params.get("date_range")
        min_importance_str = request.query_params.get("min_importance")
        emotion = request.query_params.get("emotion")
        # project スコープ: wiki ページと生記憶の両方で「同じプロジェクト」を優先する。
        from nous.domain.value_objects import normalize_project_slug

        project = normalize_project_slug(request.query_params.get("project"))
        if not q:
            return JSONResponse({"error": "Query parameter 'q' is required"}, status_code=400)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            _t0 = time.perf_counter()
            from nous.api.mcp._tools_memory import MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT
            from nous.domain.search.policy import RankPolicy

            # project 指定時は候補プールを広げる。ブーストは top_k で切った後では順位を変えられない
            # （4 位以下の project 記憶が永久に昇格できない）ので広く取ってから改めて切る。
            # 実効の pool は engine 側 `min(max(top_k*3, 15), 60)` で頭打ち（limit>=20 では元々 60）。
            # limit<20 の経路（拡張の既定 limit=3）では 15→27 に増えるので、decision gate が
            # 有効な設定では**採否も変わり得る**（順位だけの変更ではない）。
            query_kwargs: dict = {"text": q, "mode": mode, "top_k": min(100, limit * 3) if project else limit}
            if date_range:
                query_kwargs["date_range"] = date_range
            if min_importance_str:
                with __import__("contextlib").suppress(ValueError):
                    query_kwargs["min_importance"] = float(min_importance_str)
            if emotion:
                query_kwargs["emotion"] = emotion
            # Jev 型判定ゲート / multi-hop (#011): 既定は persona の ChatConfig、
            # query param で上書き（decision / hops / request_id）。
            from nous.domain.memory.query_service import resolve_decision_config

            decision_cfg = resolve_decision_config(getattr(ctx, "memory_repo", None))
            decision_raw = request.query_params.get("decision")
            decision_enabled = (
                _parse_decision_flag(decision_raw) if decision_raw is not None else bool(decision_cfg["enabled"])
            )
            max_hops = int(decision_cfg["max_hops"])
            hops_raw = request.query_params.get("hops")
            if hops_raw is not None:
                with __import__("contextlib").suppress(ValueError):
                    max_hops = max(1, min(5, int(hops_raw)))
            query_kwargs["request_id"] = request.query_params.get("request_id") or None
            if decision_enabled:
                query_kwargs["decision_enabled"] = True
                query_kwargs["decision_model"] = str(decision_cfg["model"]) or None
                query_kwargs["decision_threshold"] = float(decision_cfg["threshold"])
                query_kwargs["max_hops"] = max_hops
                query_kwargs["decision_time_weight"] = float(decision_cfg["time_weight"])
            # oracle BLOCK F3 + 重み統一: REST 経路にも RankPolicy（複合スコア段）を
            # 配線する。REST は per-call の重み引数を持たないので、ここで MCP memory_search の
            # 既定と同値（importance 0 / vector 1 / recency 既定 / keyword 既定）を固定する。
            # MCP 既定を変える時はこのブロックも合わせる（tests/unit/test_mcp_rest_rank_policy_wiring.py）。
            query_kwargs["rank_policy"] = RankPolicy.from_weight_args(
                importance_weight=0.0,
                recency_weight=MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT,
                vector_weight=1.0,
                keyword_weight=1.0,
            )
            # 被覆率項の重みは測定用に query param で上書きできる（既定は RankPolicy 既定）。
            # shortcut: 調整用の口を API に置いている（運用で固定したら Settings 化して閉じる）
            coverage_raw = request.query_params.get("coverage")
            if coverage_raw is not None:
                with __import__("contextlib").suppress(ValueError):
                    import dataclasses

                    query_kwargs["rank_policy"] = dataclasses.replace(
                        query_kwargs["rank_policy"], coverage_weight=max(0.0, float(coverage_raw))
                    )
            query = SearchQuery(**query_kwargs)
            if hasattr(ctx.search_engine, "_semantic") and ctx.search_engine._semantic is not None:
                ctx.search_engine._semantic.persona = persona  # noqa: SLF001

            result = await ctx.search_engine.search(query)
            if not isinstance(result, Success):
                return error_from_result(result)
            # 観測性（kanban #10）: レイテンシと zero-result をプロセス内に残す。
            # 記録失敗で検索を落とさない。
            try:
                from nous.infrastructure.metrics import registry as _metrics

                _metrics.observe_search(persona, (time.perf_counter() - _t0) * 1000.0, len(result.value))
            except Exception:
                logger.debug("search metrics failed", exc_info=True)
            # 発火可視化 (#011 Phase 15): 記憶に紐づく entity 層を返す。形は
            # /api/graph と同一（_merge_entity_layer を共有）ので、フロントは
            # 同じ entity 分岐で描ける。上限は既存の /api/graph 経路と同じ 50 件
            # （find_recent 依存は使わない — 類似度発火は古い記憶も当たるため）。
            entity_nodes: list = []
            entity_edges: list = []
            _merge_entity_layer(ctx, [r.memory for r in result.value], entity_nodes, entity_edges, set())
            # wiki は別枠（#16）: results[] の形は不変。失敗しても本文検索自体は返す。
            try:
                from nous.application.wiki.search import search_wiki_pages

                wiki_hits = await search_wiki_pages(ctx, persona, q, limit=3, project=project or None)
            except Exception as wiki_exc:
                logger.debug("wiki search unavailable: %s", wiki_exc)
                wiki_hits = []
            # 注入ブロック（chat と同一整形）。失敗しても本文検索・results[] は返す。
            try:
                injection = await _build_injection(ctx, persona, result.value, wiki_hits, _load_chat_config(persona))
            except Exception as injection_exc:
                logger.debug("injection build unavailable: %s", injection_exc)
                injection = ""
            results = [
                {
                    "memory": _memory_to_dict(r.memory),
                    "score": round(r.score, 4),
                    "source": r.source,
                    # engine の最終順位（score * time_weight）を再現できるように運ぶ。
                    "time_weight": r.time_weight,
                }
                for r in result.value
            ]
            return JSONResponse(
                {
                    "persona": persona,
                    "query": q,
                    "limit": limit,
                    "project": project or None,
                    "results": apply_project_boost(results, project)[:limit],
                    "wiki": wiki_hits,
                    "nodes": entity_nodes,
                    "edges": entity_edges,
                    "state": _state_digest(ctx, persona),
                    # pi 拡張はこの文字列をそのまま注入する（整形は Python 側に一本化）
                    "injection": injection,
                }
            )
        # 最終防衛線
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    # d2: GET /api/emotions/{persona} 削除（直叩き廃止。dashboard集約はcontext/statsで代替）
    # 参照は死にanalytics.py＋tests＋scripts＋docsのみ。liveタブ未使用。
    @mcp.custom_route("/api/graph/{persona}", methods=["GET"])
    async def graph_data(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        try:
            limit = int(request.query_params.get("limit", "200"))
        except ValueError:
            return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        if not 1 <= limit <= 1000:
            # 兄弟ルートと同じ上限。超過は 500 ではなく 400（#89 review）
            return JSONResponse({"error": "limit must be between 1 and 1000"}, status_code=400)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            result = ctx.memory_repo.find_recent(limit=limit)
            if not isinstance(result, Success):
                return error_from_result(result)
            memories = result.value

            nodes = []
            edges = []
            edge_set = set()
            tag_to_keys: dict[str, list[str]] = defaultdict(list)

            for mem in memories:
                nodes.append(
                    {
                        "key": mem.key,
                        "content": mem.content[:100] if mem.content else "",
                        "tags": mem.tags or [],
                        "emotion": mem.emotion,
                        "emotion_intensity": mem.emotion_intensity,
                        "importance": mem.importance,
                    }
                )
                for tag in mem.tags or []:
                    tag_to_keys[tag].append(mem.key)
                for related in mem.related_keys or []:
                    pair = tuple(sorted([mem.key, related]))
                    if pair not in edge_set:
                        edge_set.add(pair)
                        edges.append(
                            {
                                "source": mem.key,
                                "target": related,
                                "type": "related",
                            }
                        )

            for tag, keys in tag_to_keys.items():
                if len(keys) > 1:
                    capped = keys[:20]
                    for i in range(len(capped)):
                        for j in range(i + 1, len(capped)):
                            pair = tuple(sorted([capped[i], capped[j]]))
                            if pair not in edge_set:
                                edge_set.add(pair)
                                edges.append(
                                    {
                                        "source": capped[i],
                                        "target": capped[j],
                                        "type": "tag",
                                        "tag": tag,
                                    }
                                )

            _merge_entity_layer(ctx, memories, nodes, edges, edge_set)

            return JSONResponse(
                {
                    "persona": persona,
                    "nodes": nodes,
                    "edges": edges,
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                }
            )
        # 最終防衛線
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)
