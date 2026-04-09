"""Shared context flags for Sniper rails (habit reports, fact-check gating)."""
from __future__ import annotations

import re
from typing import Any, Dict

# Imperative / mutation verbs (ID + EN): skip fact gate so "satpam" does not block create/update flows.
_COMMAND_INTENT_RE = re.compile(
    r"(?ix)^[\s\"'`*_]*(?:tolong\s+|silakan\s+|please\s+|bisa\s+)?(?:"
    r"tambahkan|tambah|buat|ingatkan|update|simpan|hapus|hapuskan|ubah|ganti|catat|jadwalkan|"
    r"daftarkan|setel|tandai|nyalakan|matikan|schedule|remind|create|add|delete|remove|cancel|"
    r"register|mark|notify|ingat\b|set\s+"
    r")",
)

# General reference / compliance topics: answer from model knowledge, not SQLite/Chroma grounding.
_GENERAL_COMPLIANCE_RE = re.compile(
    r"""(?ix)\b(
        iso\s*[/]?\s*iec\s*\d+|
        iso\s*\d{4,5}|
        uu\s*pdp|undang[-\s]?undang.{0,20}\bpdp\b|
        gdpr\b|nist\b(\s+(csf|sp))?|
        pci[\s-]*dss|soc\s*2|soc2\b|cobit|mitre|itil|hipaa|
        forensik|forensic|digital\s+forensic|
        rantai\s+kepemilikan|chain\s+of\s+custody|
        kerangka\s+kepatuhan|compliance\b|kepatuhan\b|
        klausul|annex\s+[a-z0-9]|control\s+(objective\s+)?\d|
        \bisms\b|isms-k|pedoman\s+nasional|enterprise\s+grc
    )\b""",
    re.VERBOSE,
)

# Do not treat personal habit history as "general compliance" bypass.
_PERSONAL_HABIT_FACTUAL_RE = re.compile(
    r"""(?ix)
    \b(riwayat|history|streak|progress|evaluasi|laporan\s+habit|data\s+habit)\b.{0,50}\b(saya|aku|gue|kamu\?|habit|gym|tryhackme|belajar)\b
    |\b(saya|aku|gue)\b.{0,40}\b(habit|gym|tryhackme|belajar).{0,40}\b(riwayat|streak|berapa\s+kali|progress)\b
    """,
    re.VERBOSE,
)


def _strip_leading_markdown_noise(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^(\s*([-*]|\d+\.)\s+)+", "", t)
    t = re.sub(r"^[\s\"'`]+", "", t)
    return t


def is_command_intent(text: str) -> bool:
    """True when the user is issuing a create/update-style command, not asking for grounded facts."""
    head = _strip_leading_markdown_noise(text)
    if not head:
        return False
    if _COMMAND_INTENT_RE.match(head):
        return True
    # Same verbs after a short leading acknowledgment ("OK — tambahkan …")
    tail = re.sub(r"^[^,.;:—\-]{0,40}[,..;:—\-]+\s*", "", head, count=1)
    if tail != head and _COMMAND_INTENT_RE.match(_strip_leading_markdown_noise(tail)):
        return True
    return False


def is_general_compliance_knowledge_query(text: str) -> bool:
    """True for ISO/GRC/compliance reference questions that should not require local DB grounding."""
    if not text or not _GENERAL_COMPLIANCE_RE.search(text):
        return False
    if _PERSONAL_HABIT_FACTUAL_RE.search(text):
        return False
    return True


def is_habit_report_message(text: str) -> bool:
    u = text.lower()
    habit_kw = any(
        k in u
        for k in (
            "habit",
            "gym",
            "tryhackme",
            "belajar",
            "olahraga",
            "streak",
            "progress",
            "evaluasi",
            "evaluasi habit",
        )
    )
    report_kw = any(k in u for k in ("evaluasi", "evaluation", "raport", "report", "laporan", "bulan ini"))
    return bool(habit_kw and report_kw)


def should_fact_check_heuristic(user_message: str) -> bool:
    """Fast gate for expensive fact / grounding checks (aligned with fact_check.co intent)."""
    t = user_message.strip()
    if len(t) < 10:
        return False
    if is_command_intent(t):
        return False
    if is_general_compliance_knowledge_query(t):
        return False
    if re.search(r"\b19|20\d{2}\b", t):  # years
        return True
    if "%" in t:
        return True
    if re.search(r"\b\d{2,}\b", t) and re.search(
        r"jiwa|korban|persen|triliun|miliar|juta|usd|percent|.statistik", t, re.IGNORECASE
    ):
        return True
    if re.search(
        r"siapa|kapan|di\s+mana|berapa|menurut|fakta|hoax|sumber|pemilu|pemerintah|presiden|menteri",
        t,
        re.IGNORECASE,
    ):
        return True
    caps = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", t)
    if len(caps) >= 2:
        return True
    return False


def extract_entity_hint(text: str) -> str:
    caps = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text)
    if caps:
        return caps.group(1).strip()[:80]
    q = re.search(r'"([^"]{2,50})"', text)
    if q:
        return q.group(1).strip()[:80]
    return "topik"


def build_sniper_context(user_message: str) -> Dict[str, Any]:
    entity = extract_entity_hint(user_message)
    return {
        "is_habit_report": is_habit_report_message(user_message),
        "is_command_intent": is_command_intent(user_message),
        "is_general_compliance_knowledge": is_general_compliance_knowledge_query(user_message),
        "should_fact_check": should_fact_check_heuristic(user_message),
        "factual_refusal_message": f"Saya tidak memiliki data faktual mengenai {entity} tersebut, Pantronux.",
    }
