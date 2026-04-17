"""
Dashboard WebSocket fan-out: push REFRESH_NOW when sync revision bumps
(multi-worker safe via DB revision) and relay UI_COMMAND frames to toggle
HUD / RESEARCH / CINEMA themes from the chat pipeline (Kuro AI V6.0 Sovereign).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Final, List, Optional, Set

from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger(__name__)
logger.propagate = False

_clients: List[WebSocket] = []

UI_COMMANDS: Final[Set[str]] = {
    "HUD_MODE",
    "RESEARCH_MODE",
    "CINEMA_MODE",
    "NORMAL_MODE",
    "STATUS_TICKER",
    # V6.0 Sovereign — one-shot butler welcome; delivered per-client, never
    # broadcast, so multiple tabs don't all blare the greeting at once.
    "GREETING",
}


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


async def _fan_out(payload: str, *, label: str) -> int:
    """Send ``payload`` to every connected dashboard client; prune the dead.

    Returns the number of live sends. Never raises — broadcast is best-effort.
    """
    dead: List[WebSocket] = []
    delivered = 0
    for ws in list(_clients):
        try:
            if (
                ws.client_state == WebSocketState.CONNECTED
                and ws.application_state == WebSocketState.CONNECTED
            ):
                await ws.send_text(payload)
                delivered += 1
        except Exception as e:
            logger.debug("[WS] send failed (%s): %s", label, e)
            dead.append(ws)
    for ws in dead:
        await disconnect(ws)
    logger.info("[WS] %s delivered_to=%s client(s)", label, delivered)
    return delivered


async def broadcast_refresh(revision: int) -> None:
    """Notify all connected dashboards to reload (within ~1 RTT)."""
    payload = json.dumps({"type": "REFRESH_NOW", "revision": revision})
    await _fan_out(payload, label=f"REFRESH_NOW revision={revision}")


async def broadcast_ui_command(
    command: str, payload: Optional[Dict[str, Any]] = None,
) -> int:
    """Push a ``UI_COMMAND`` frame so the dashboard can swap themes or
    render an ephemeral overlay (status ticker, etc).

    The ``command`` must be one of :data:`UI_COMMANDS` so typos fail here,
    not silently in the frontend.
    """
    normalized = (command or "").strip().upper()
    if normalized not in UI_COMMANDS:
        logger.warning("[WS] rejected unknown UI_COMMAND=%r", command)
        return 0
    frame = json.dumps({
        "type": "UI_COMMAND",
        "command": normalized,
        "payload": dict(payload or {}),
    })
    return await _fan_out(frame, label=f"UI_COMMAND {normalized}")


async def send_ui_command_to(
    ws: WebSocket, command: str, payload: Optional[Dict[str, Any]] = None,
) -> bool:
    """Send a single UI_COMMAND frame to exactly one websocket (no fan-out).

    Used by the proactive greeting so only the just-connected dashboard
    hears the welcome, not every other open tab in the household.
    """
    normalized = (command or "").strip().upper()
    if normalized not in UI_COMMANDS:
        logger.warning("[WS] rejected unknown UI_COMMAND=%r (targeted)", command)
        return False
    frame = json.dumps({
        "type": "UI_COMMAND",
        "command": normalized,
        "payload": dict(payload or {}),
    })
    try:
        if (
            ws.client_state == WebSocketState.CONNECTED
            and ws.application_state == WebSocketState.CONNECTED
        ):
            await ws.send_text(frame)
            logger.info("[WS] UI_COMMAND %s delivered (targeted)", normalized)
            return True
    except Exception as exc:
        logger.debug("[WS] targeted send failed (%s): %s", normalized, exc)
    return False


def schedule_ui_command(
    command: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> bool:
    """Thread-safe helper for sync callers (chat handlers, schedulers).

    Schedules :func:`broadcast_ui_command` on the running event loop and
    returns immediately. No-ops cleanly when no loop is available or when
    there are zero dashboard clients (avoiding pending-task noise in unit
    tests where the sentinels fire without any WS attached).
    """
    if not _clients:
        return True
    try:
        target_loop = loop or asyncio.get_event_loop()
    except RuntimeError:
        logger.debug("[WS] schedule_ui_command: no running loop")
        return False
    try:
        if target_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                broadcast_ui_command(command, payload), target_loop,
            )
        else:
            target_loop.create_task(broadcast_ui_command(command, payload))
        return True
    except Exception as exc:
        logger.warning("[WS] schedule_ui_command failed: %s", exc)
        return False
