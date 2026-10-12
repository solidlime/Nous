from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import (
    _memory_to_dict,
    _resolve_persona_from_request,
    _safe_get_context,
)
from nous.api.http.routers._error_handlers import error_from_result
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)

# decision クエリパラメータ（0/1/true/false）の真値集合（最小パース）。
_TRUTHY_VALUES = frozenset({"1", "true", "on", "yes"})


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

    FYI(accepted): tags also surface as concept entities (see domain/memory/graph.py),
    and enrich runs async, so relations may be missing within the 30s cache window.
    """
    # getattr guard keeps the endpoint backward-compatible until Lane B lands.
    get_entities = getattr(ctx.entity_repo, "get_entities_for_memories", None)
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

    get_relations = getattr(ctx.entity_repo, "get_relations_between_entities", None)
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
            return JSONResponse({"error": "limit must be between 1 and 100"}, status_code=400)
        limit = min(limit, 100)
        mode = request.query_params.get("mode", "hybrid")
        date_range = request.query_params.get("date_range")
        min_importance_str = request.query_params.get("min_importance")
        emotion = request.query_params.get("emotion")
        if not q:
            return JSONResponse({"error": "Query parameter 'q' is required"}, status_code=400)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            from nous.api.mcp._tools_memory import MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT
            from nous.domain.search.engine import SearchQuery
            from nous.domain.search.policy import RankPolicy

            query_kwargs: dict = {"text": q, "mode": mode, "top_k": limit}
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
            # 配線する。重みは MCP memory_search の既定と同一（from_weight_args 経由）。
            # 実利用経路は MCP であり実クエリで高い実績を持つため統一先は MCP 既定。
            # 引数・戻り値の形式は不変（変わるのは順位のみ）。
            query_kwargs["rank_policy"] = RankPolicy.from_weight_args(
                importance_weight=0.0,
                recency_weight=MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT,
                vector_weight=1.0,
                keyword_weight=1.0,
            )
            query = SearchQuery(**query_kwargs)
            if hasattr(ctx.search_engine, "_semantic") and ctx.search_engine._semantic is not None:
                ctx.search_engine._semantic.persona = persona  # noqa: SLF001

            result = await ctx.search_engine.search(query)
            if not result.is_ok:
                return error_from_result(result)
            # 発火可視化 (#011 Phase 15): 記憶に紐づく entity 層を返す。形は
            # /api/graph と同一（_merge_entity_layer を共有）ので、フロントは
            # 同じ entity 分岐で描ける。上限は既存の /api/graph 経路と同じ 50 件
            # （find_recent 依存は使わない — 類似度発火は古い記憶も当たるため）。
            entity_nodes: list = []
            entity_edges: list = []
            _merge_entity_layer(ctx, [r.memory for r in result.value], entity_nodes, entity_edges, set())
            return JSONResponse(
                {
                    "persona": persona,
                    "query": q,
                    "limit": limit,
                    "results": [
                        {
                            "memory": _memory_to_dict(r.memory),
                            "score": round(r.score, 4),
                            "source": r.source,
                        }
                        for r in result.value
                    ],
                    "nodes": entity_nodes,
                    "edges": entity_edges,
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
        limit = int(request.query_params.get("limit", "200"))
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            result = ctx.memory_repo.find_recent(limit=limit)
            if not result.is_ok:
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
