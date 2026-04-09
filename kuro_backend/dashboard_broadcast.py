"""
Dashboard WebSocket fan-out: push REFRESH_NOW when sync revision bumps (multi-worker safe via DB revision).
"""
from __future__ import annotations

import json
import logging
from typing import List

from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger(__name__)
logger.propagate = False

_clients: List[WebSocket] = []


async def connect(ws: WebSocket) -> None:
    await ws.accept()
    _clients.append(ws)
    logger.debug("[WS] dashboard client connected (total=%s)", len(_clients))


async def disconnect(ws: WebSocket) -> None:
    try:
        _clients.remove(ws)
    except ValueError:
        pass
    logger.debug("[WS] dashboard client removed (total=%s)", len(_clients))


async def broadcast_refresh(revision: int) -> None:
    """Notify all connected dashboards to reload (within ~1 RTT)."""
    payload = json.dumps({"type": "REFRESH_NOW", "revision": revision})
    dead: List[WebSocket] = []
    for ws in list(_clients):
        try:
            if (
                ws.client_state == WebSocketState.CONNECTED
                and ws.application_state == WebSocketState.CONNECTED
            ):
                await ws.send_text(payload)
        except Exception as e:
            logger.debug("[WS] send failed: %s", e)
            dead.append(ws)
    for ws in dead:
        await disconnect(ws)
    logger.info(
        "[WS] REFRESH_NOW revision=%s delivered_to=%s client(s)",
        revision,
        max(0, len(_clients)),
    )
