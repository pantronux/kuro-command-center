"""
Kuro AI V6.0 Sovereign — Async adapter for synchronous SSoT writers.

SSoT rule (see `services/core_service.py`): `bump_data_revision()` and
`record_mutation()` + the `*_svc` wrappers MUST remain synchronous. FastAPI
endpoints are `async def` though, so calling them directly blocks the event
loop — a slow SQLite query stalls WebSocket broadcasts and SSE streams.

This module provides a single, typed bridge: `run_db()` offloads a synchronous
callable to a worker thread via `asyncio.to_thread`. No wrapping beyond that —
callers keep ownership of error handling, types, and return shape.

Usage:
    from kuro_backend.services import async_adapter
    habits = await async_adapter.run_db(core_service.list_habits_validated)
    await async_adapter.run_db(core_service.add_habit_svc, name="read", target=30)
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


async def run_db(fn: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> R:
    """Run a synchronous DB callable in a worker thread.

    Preserves the callable's exception surface — exceptions raised inside
    the worker thread are re-raised by `asyncio.to_thread` in the caller's
    event loop.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


def as_awaitable(fn: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> Awaitable[R]:
    """Convenience alias for call-sites that prefer Awaitable typing."""
    return run_db(fn, *args, **kwargs)
