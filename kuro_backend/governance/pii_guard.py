from __future__ import annotations

import re


def redact_pii(text: str) -> str:
    if not text:
        return ""
    out = re.sub(r"(?i)(api[_-]?key\s*[:=]\s*)([^\s]+)", r"\1[REDACTED]", text)
    out = re.sub(r"(?i)(password\s*[:=]\s*)([^\s]+)", r"\1[REDACTED]", out)
    return out
