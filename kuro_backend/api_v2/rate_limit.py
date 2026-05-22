"""Permissive-by-default API V2 rate limit primitives."""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Mapping, Optional, Protocol, Tuple


ROUTE_CLASS_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/api/chat", "chat"),
    ("/api/v2/chat", "chat"),
    ("/api/market", "market"),
    ("/api/market-v2", "market"),
    ("/api/v2/market", "market"),
    ("/api/tools/deep-research", "research"),
    ("/api/v2/research", "research"),
    ("/api/telegram", "telegram"),
)


@dataclass(frozen=True)
class RateLimitRule:
    requests: int
    window_seconds: int = 60


@dataclass(frozen=True)
class RateLimitRequest:
    identifier: str
    route_class: str
    path: str
    method: str
    now: float


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int = 0
    remaining: int = 0
    reset_after_seconds: int = 0
    reason: str = ""


class RateLimiter(Protocol):
    def check(self, request: RateLimitRequest) -> RateLimitDecision:
        ...


class DisabledRateLimiter:
    def check(self, request: RateLimitRequest) -> RateLimitDecision:
        return RateLimitDecision(allowed=True)


class InMemoryRateLimiter:
    def __init__(self, rules: Optional[Mapping[str, RateLimitRule]] = None) -> None:
        self.rules = dict(rules or {})
        self._buckets: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)

    def check(self, request: RateLimitRequest) -> RateLimitDecision:
        rule = self.rules.get(request.route_class) or self.rules.get("default")
        if rule is None or rule.requests <= 0:
            return RateLimitDecision(allowed=True)

        key = (request.identifier, request.route_class)
        bucket = self._buckets[key]
        cutoff = request.now - max(1, int(rule.window_seconds))
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= rule.requests:
            reset_after = int(max(1, round(bucket[0] + rule.window_seconds - request.now)))
            return RateLimitDecision(
                allowed=False,
                limit=rule.requests,
                remaining=0,
                reset_after_seconds=reset_after,
                reason="rate limit exceeded",
            )

        bucket.append(request.now)
        return RateLimitDecision(
            allowed=True,
            limit=rule.requests,
            remaining=max(0, rule.requests - len(bucket)),
            reset_after_seconds=max(1, int(rule.window_seconds)),
        )


def route_class_for_path(path: str) -> str:
    normalized = path or ""
    for prefix, route_class in ROUTE_CLASS_PREFIXES:
        if normalized.startswith(prefix):
            return route_class
    return "default"


def rate_limit_identifier(headers: Mapping[str, str], client_host: str) -> str:
    username = (
        headers.get("x-kuro-username")
        or headers.get("x-authenticated-user")
        or headers.get("x-user")
        or ""
    ).strip()
    if username:
        return f"user:{username}"
    return f"ip:{client_host or 'unknown'}"


def env_rate_limit_enabled() -> bool:
    return os.getenv("KURO_API_V2_RATE_LIMIT_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def rules_from_env() -> Dict[str, RateLimitRule]:
    default_per_minute = int(os.getenv("KURO_API_V2_RATE_LIMIT_PER_MIN", "0") or "0")
    rules: Dict[str, RateLimitRule] = {}
    if default_per_minute > 0:
        rules["default"] = RateLimitRule(requests=default_per_minute, window_seconds=60)
    for route_class in ("chat", "market", "research", "telegram"):
        raw = os.getenv(f"KURO_API_V2_RATE_LIMIT_{route_class.upper()}_PER_MIN", "")
        if raw.strip():
            rules[route_class] = RateLimitRule(requests=int(raw), window_seconds=60)
    return rules


def default_rate_limiter() -> RateLimiter:
    if not env_rate_limit_enabled():
        return DisabledRateLimiter()
    return InMemoryRateLimiter(rules_from_env())


def build_rate_limit_request(
    *,
    headers: Mapping[str, str],
    client_host: str,
    path: str,
    method: str,
) -> RateLimitRequest:
    return RateLimitRequest(
        identifier=rate_limit_identifier(headers, client_host),
        route_class=route_class_for_path(path),
        path=path,
        method=method,
        now=time.monotonic(),
    )
