"""Small pagination helpers for API V2 route implementations."""
from __future__ import annotations

import base64
from typing import Any, Iterable, List, Optional, Tuple

from pydantic import BaseModel, Field

from kuro_backend.api_v2.schemas import PaginationMeta


class PageParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    cursor: Optional[str] = None


def encode_cursor(offset: int) -> str:
    raw = str(max(0, int(offset))).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        return max(0, int(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")))
    except Exception:
        return 0


def paginate_items(items: Iterable[Any], params: PageParams) -> Tuple[List[Any], PaginationMeta]:
    all_items = list(items)
    offset = decode_cursor(params.cursor)
    limit = max(1, min(int(params.limit or 50), 500))
    page = all_items[offset : offset + limit]
    next_offset = offset + len(page)
    next_cursor = encode_cursor(next_offset) if next_offset < len(all_items) else None
    return page, PaginationMeta(limit=limit, next_cursor=next_cursor, total=len(all_items))
