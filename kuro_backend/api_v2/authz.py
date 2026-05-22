"""API V2 RBAC helpers built on top of existing Kuro auth dependencies."""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, Iterable, Optional

from fastapi import Depends, HTTPException

from kuro_backend.api_v2.schemas import Principal


ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_AUDITOR = "auditor"
ROLE_SERVICE_ACCOUNT = "service_account"
KNOWN_ROLES = {ROLE_ADMIN, ROLE_USER, ROLE_AUDITOR, ROLE_SERVICE_ACCOUNT}


def _csv_env(name: str) -> set[str]:
    return {part.strip() for part in os.getenv(name, "").split(",") if part.strip()}


def principal_from_user(user: Dict[str, Any]) -> Principal:
    username = str((user or {}).get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    admin_username = os.getenv("ADMIN_USERNAME", "Pantronux")
    roles = {ROLE_USER}
    if username == admin_username:
        roles.add(ROLE_ADMIN)
    if username in _csv_env("KURO_AUDITOR_USERNAMES"):
        roles.add(ROLE_AUDITOR)
    if username in _csv_env("KURO_SERVICE_ACCOUNT_USERNAMES") or username.startswith("svc_"):
        roles.add(ROLE_SERVICE_ACCOUNT)

    try:
        from kuro_backend import auth_db

        user_info = auth_db.get_user(username) or {}
        registry_role = str(user_info.get("role") or "").strip().lower()
        if registry_role in KNOWN_ROLES:
            roles.add(registry_role)
    except Exception:
        pass

    raw_roles = (user or {}).get("roles") or []
    if isinstance(raw_roles, str):
        raw_roles = [raw_roles]
    for role in raw_roles:
        normalized = str(role or "").strip().lower()
        if normalized in KNOWN_ROLES:
            roles.add(normalized)

    return Principal(
        username=username,
        roles=sorted(roles),
        is_admin=ROLE_ADMIN in roles,
        is_service_account=ROLE_SERVICE_ACCOUNT in roles,
    )


def has_any_role(principal: Principal, roles: Iterable[str]) -> bool:
    wanted = {str(role).strip().lower() for role in roles}
    return bool(wanted.intersection(set(principal.roles)))


def require_roles(principal: Principal, roles: Iterable[str]) -> Principal:
    if not has_any_role(principal, roles):
        raise HTTPException(status_code=403, detail="Forbidden")
    return principal


def require_admin(principal: Principal) -> Principal:
    return require_roles(principal, [ROLE_ADMIN])


def role_dependency(
    auth_dependency: Callable[..., Dict[str, Any]],
    *,
    roles: Iterable[str],
) -> Callable[..., Principal]:
    def _dependency(user: Dict[str, Any] = Depends(auth_dependency)) -> Principal:
        return require_roles(principal_from_user(user), roles)

    return _dependency


def admin_dependency(auth_dependency: Callable[..., Dict[str, Any]]) -> Callable[..., Principal]:
    return role_dependency(auth_dependency, roles=[ROLE_ADMIN])


def principal_dependency(auth_dependency: Callable[..., Dict[str, Any]]) -> Callable[..., Principal]:
    def _dependency(user: Dict[str, Any] = Depends(auth_dependency)) -> Principal:
        return principal_from_user(user)

    return _dependency
