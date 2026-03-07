"""
HTTP Webhook 送受信アダプター。

受信: POST /api/webhook/receive/{persona} → EventBus にイベント投入
送信: send_webhook(url, payload) → 外部 URL に POST
"""

import logging
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhook", tags=["webhook"])


@router.post("/receive/{persona}")
async def receive_webhook(persona: str, request: Request):
    """外部からの Webhook を受信してエージェントに転送する。

    設定に `webhook.inbound_secret` が指定されている場合は
    X-Webhook-Secret ヘッダーで認証する。
    """
    from config import load_config
    cfg = load_config()

    # 認証チェック（任意）
    secret = cfg.get("webhook", {}).get("inbound_secret", "")
    if secret:
        incoming_secret = request.headers.get("X-Webhook-Secret", "")
        if incoming_secret != secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # ペイロード取得
    try:
        body = await request.json()
    except Exception:
        body = {}

    logger.info(f"Webhook 受信: persona={persona}, payload={str(body)[:100]}")

    # AgentLoop の EventBus に投入
    from nous_mcp.tools.agent_tools import _agent_loops
    loop = _agent_loops.get(persona)
    if loop is not None and getattr(loop, "_event_bus", None) is not None:
        from agent.event_bus import AgentEvent, EventType
        event = AgentEvent(
            priority=2,
            event_type=EventType.WEBHOOK_RECEIVED,
            persona=persona,
            data={
                "payload": body,
                "source_ip": request.client.host if request.client else None,
                "headers": dict(request.headers),
            },
        )
        try:
            await loop._event_bus.put(event)
            logger.debug(f"Webhook イベントをバスに投入: {persona}")
        except Exception as e:
            logger.error(f"Webhook イベント投入失敗: {e}")

    return {"success": True, "persona": persona}


async def send_webhook(
    url: str,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 10,
) -> bool:
    """外部 URL に Webhook を送信する。

    Args:
        url: 送信先 URL。
        payload: JSON ペイロード。
        headers: 追加 HTTP ヘッダー（任意）。
        timeout: タイムアウト秒数（デフォルト 10）。

    Returns:
        HTTP 4xx/5xx 以外なら True。
    """
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                success = resp.status < 400
                if not success:
                    logger.warning(
                        f"Webhook 送信: HTTP {resp.status} → {url}"
                    )
                else:
                    logger.debug(f"Webhook 送信成功: {url}")
                return success
    except aiohttp.ClientConnectorError:
        logger.warning(f"Webhook 接続失敗: {url}")
        return False
    except Exception as e:
        logger.error(f"Webhook 送信エラー → {url}: {e}")
        return False


async def broadcast_webhooks(
    persona: str,
    payload: Dict[str, Any],
) -> List[bool]:
    """設定に登録された送信先全てに Webhook をブロードキャストする。

    config の `webhook.personas.{persona}.outbound_urls` リストに送信する。

    Args:
        persona: ペルソナ名。
        payload: 送信するペイロード。

    Returns:
        各 URL の送信結果（True/False）のリスト。
    """
    from config import load_config
    cfg = load_config()
    urls: List[str] = (
        cfg.get("webhook", {})
        .get("personas", {})
        .get(persona, {})
        .get("outbound_urls", [])
    )

    results = []
    for url in urls:
        result = await send_webhook(url, payload)
        results.append(result)
    return results
