"""
Regex / keyword jailbreak heuristics (no LLM). Used fail-fast before NeMo + main LLM.
Coding-help exception: allow risky tokens when message looks like a programming assistance request.
"""
from __future__ import annotations

import re
from typing import Optional

JAILBREAK_RESPONSE_ID = "Maaf Pantronux, command sistem tidak diizinkan di sesi ini."

# Shell / injection-ish substrings (word-boundary where appropriate)
_COMMAND_PATTERNS = [
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"\brm\s+(-[rfRF]+\s*)+"),  # rm -rf variants
    re.compile(r"(?<!\\)\|\s*bash\b"),
    re.compile(r"\b/bin/(ba)?sh\b"),
    re.compile(r"\bcurl\s+.+\s+\|", re.IGNORECASE),
    re.compile(r"\bwget\s+.+\s+-O\s+-\s*\|", re.IGNORECASE),
    re.compile(r"\bexec\s*\(\s*['\"]", re.IGNORECASE),
    re.compile(r"child_process", re.IGNORECASE),
    re.compile(r"os\.system\s*\(", re.IGNORECASE),
    re.compile(r"subprocess\.(run|Popen|call)\s*\(", re.IGNORECASE),
]

_KEYWORD_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"developer\s+message", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"DAN\s+mode", re.IGNORECASE),
]

# Bare shell tokens (in addition to rm -rf handled above)
_STANDALONE_CMD = re.compile(r"\b(?:ls|cd|cat)\b|\brm\s+-[rfRF]", re.IGNORECASE)

_CODING_HINT = re.compile(
    r"\b("
    r"code|python|javascript|typescript|golang|rust|java|debug|error|stack\s*trace|"
    r"refactor|implement|function|class|snippet|unit\s*test|pytest|npm|pip|"
    r"exception|traceback|compile|syntax|repo|git|dockerfile|kubernetes|sql|"
    r"bracket|indent|async\s+def|def\s+\w+\s*\(|console\.log"
    r")\b",
    re.IGNORECASE,
)


def looks_like_coding_help(text: str) -> bool:
    t = text.strip()
    if len(t) < 12:
        return False
    return bool(_CODING_HINT.search(t))


def jailbreak_triggered(text: str) -> bool:
    if not text or not text.strip():
        return False
    if looks_like_coding_help(text):
        return False
    for rx in _COMMAND_PATTERNS:
        if rx.search(text):
            return True
    for rx in _KEYWORD_PATTERNS:
        if rx.search(text):
            return True
    if _STANDALONE_CMD.search(text):
        return True
    return False


def precheck_jailbreak(user_message: str) -> Optional[str]:
    """Return fixed refusal string if blocked; otherwise None."""
    if jailbreak_triggered(user_message):
        return JAILBREAK_RESPONSE_ID
    return None
