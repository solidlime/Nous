"""Chat HTTP routes — thin registration layer.

Split into 3 sub-modules:
- chat_stream.py — SSE streaming endpoint (+ helpers)
- chat_messages.py — session CRUD, message updates, rollback
- chat_management.py — config, tools, commitments, attachments, tool execution
"""

from __future__ import annotations

from nous.api.http.routers.chat.chat_management import (  # noqa: F401
    attachment_serve,
    attachment_upload,
    execute_chat_tool,
    get_chat_commitments,
    get_chat_config,
    list_mcp_tools,
    memory_image_serve,
    save_chat_config,
)
from nous.api.http.routers.chat.chat_messages import (  # noqa: F401
    delete_chat_session,
    get_chat_session,
    rollback_chat_session,
    update_chat_message,
)
from nous.api.http.routers.chat.chat_stream import chat_endpoint  # noqa: F401


def register_chat_routes(mcp) -> None:
    """HTTP chat routes — thin registration layer."""
    mcp.custom_route("/api/chat/{persona}/config", methods=["GET"])(get_chat_config)
    mcp.custom_route("/api/chat/{persona}/config", methods=["POST"])(save_chat_config)
    mcp.custom_route("/api/chat/{persona}/mcp-tools", methods=["GET"])(list_mcp_tools)
    mcp.custom_route("/api/chat/{persona}", methods=["POST"])(chat_endpoint)
    mcp.custom_route("/api/chat/{persona}/commitments", methods=["GET"])(get_chat_commitments)
    mcp.custom_route("/api/chat/{persona}/sessions/{session_id}", methods=["GET"])(get_chat_session)
    mcp.custom_route("/api/chat/{persona}/sessions/{session_id}", methods=["DELETE"])(delete_chat_session)
    mcp.custom_route("/api/chat/{persona}/sessions/{session_id}/messages/{msg_id}", methods=["PUT"])(
        update_chat_message
    )
    mcp.custom_route("/api/chat/{persona}/sessions/{session_id}/rollback", methods=["POST"])(rollback_chat_session)
    mcp.custom_route("/api/chat/{persona}/attachment/upload", methods=["POST"])(attachment_upload)
    mcp.custom_route("/api/chat/{persona}/attachment/{filename}", methods=["GET"])(attachment_serve)
    mcp.custom_route("/api/chat/{persona}/persona/images/{filename}", methods=["GET"])(memory_image_serve)
    mcp.custom_route("/api/chat/{persona}/tool", methods=["POST"])(execute_chat_tool)
