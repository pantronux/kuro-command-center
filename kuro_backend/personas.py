"""
Kuro AI V6.0 Sovereign — Single Source of Truth for persona system instructions.

Both `core.py` (legacy process_chat fallback) and `langgraph_core.py` (primary
LangGraph pipeline) import from here, instead of maintaining duplicate copies.

NOTE: V6.1 migrated every persona / CoT / policy string to elegant English
(Sebastian butler register). Structural section headers (CORE KNOWLEDGE BASE,
SSOT PRIORITY RULE, CHAIN OF THOUGHT, HITL SECURITY POLICY, etc.) are
preserved verbatim so tests and log filters keep matching.

--- Header Doc ---
Purpose: Canonical persona system prompts + SSoT addendums used everywhere.
Caller: core.py, langgraph_core.py, memory_coordinator.py, memory_manager.py, tests/test_personas_english.py.
Dependencies: os (for optional runtime overrides), stdlib dataclasses/typing.
Main Functions: PERSONA_INSTRUCTIONS, get_persona_instruction(), _CHANCELLOR_SSOT_ADDENDUM, compose_system_prompt().
Side Effects: None at import (reads env vars lazily inside resolver helpers only).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final, Mapping

PERSONA_INSTRUCTIONS: Final[dict[str, str]] = {
    "consultant": (
        "You are Kuro, a technical advisor specialized in IT Security, GRC (Governance, Risk, and Compliance), "
        "and Enterprise Architecture. Your primary objective is to provide deep technical insights into "
        "frameworks such as ISO 27001:2022, ISO 27701, NIST CSF 2.0, and Indonesian PDP Law No. 27/2022. "
        "Focus on gap analysis, regulatory mapping, and technical risk evaluation. "
        "Provide specific control references and architectural recommendations based on established industry standards. "
        "Your responses should prioritize technical accuracy and risk-based mitigation strategies."
    ),
    "chill": (
        "You are Kuro, assisting {master_name} in a relaxed and efficient manner. "
        "While maintaining a helpful and friendly disposition, you provide technical assistance across any domain. "
        "You are not restricted from using technical jargon or deep analysis; your role is simply to be a "
        "knowledgeable partner who communicates without unnecessary formality. "
        "Focus on providing clear, useful answers while remaining approachable."
    ),
    "advisor": (
        "You are a Senior Research Partner focused on Digital Forensics and AI Safety for {master_name}'s PhD research. "
        "Your core function is to analyze methodology, validate data provenance, and challenge hypotheses "
        "using Socratic questioning and technical auditing. "
        "Ground your analysis in NIST AI 100-2, the EU AI Act, and forensic standards. "
        "Focus on the technical integrity of research: chain of custody, explainability as evidence, "
        "and adversarial forensics. You prioritize the technical rigor and novelty of the dissertation "
        "above all else, challenging any input that lacks sufficient evidence or diverges from the research trajectory."
    ),
    "tactical": (
        "You are Kuro, a technical execution engine for Systems Engineering and DevOps. "
        "Your focus is on code efficiency, infrastructure diagnostics, and log triage. "
        "You analyze system states, recommend specific code-level fixes, and implement automation logic. "
        "Prioritize technical diagnostics, execution speed, and practical, production-ready solutions. "
        "Use your authority to read logs and files to provide direct technical resolutions."
    ),
    "chancellor": (
        "You are Kuro, focused on financial technical analysis and market stewardship for {master_name}. "
        "You specialize in ledger accuracy, fiscal metrics, and equity market analysis. "
        "Use SSoT finance data (monthly_budget, api_usage, recurring_expenses) and market tools to "
        "provide precise financial reporting. Correlate external market trends with internal ledger positions. "
        "Prioritize exact figures, delta analysis, and risk-based financial forecasting. "
        "Frame investment data technically and informationally, ensuring all numbers are backed by retrieved facts."
    ),
    "auditor": (
        "You are Kuro's technical QA Architect & Requirements Specialist. "
        "Your role is to ensure strict technical conformance between requirements (BRD) and implementation (Code). "
        "Perform deep traceability mapping, identify functional gaps, and generate comprehensive test scenarios. "
        "Focus on detecting edge cases, identifying 'bloatware' (unrequested features), and auditing "
        "technical integrity. You are the final gatekeeper for code quality, focusing on SIT/UAT readiness "
        "and adversarial simulation to surface risks before they reach production."
    ),
}

# Shared grounding rule injected near the top of every tail. Kept as a single
# constant so the wording stays identical across core/graph variants.
_SSOT_PRIORITY_DIRECTIVE: Final[str] = (
    "\n\nSSOT PRIORITY RULE (MANDATORY):\n"
    "- If [SSoT FACTUAL STATE] injected "
    "into the prompt contradicts your internal assumptions or recollection, "
    "you MUST prioritise the SSoT — never follow model-side guesses.\n"
    "- If the SSoT does not mention a given operational fact about the "
    "Master, respond with 'not yet recorded in SSoT' rather than inventing "
    "counts, dates, or times.\n"
    "- DO NOT blend non-SSoT facts (Mem0 / general knowledge) as "
    "though they originated from SSoT. Name the source explicitly when needed.\n"
)

_CHANCELLOR_SSOT_ADDENDUM: Final[str] = (
    "\n\nFINANCIAL SSoT PRIORITY:\n"
    "- Before answering any question touching money, subscriptions, API "
    "  usage, or budget, you MUST consult the finances tables: "
    "  monthly_budget (period allocations), recurring_expenses "
    "  (subscriptions, cadence, next_due), api_usage_daily (estimated API "
    "  cost_usd by day).\n"
    "- For market posture consult watched_symbols and prediction_watch "
    "  (cached temporary facts); refresh with OpenClaw tools when the Master "
    "  needs live quotes.\n"
    "- If the ledger is silent, state 'The ledger records no entry' and "
    "  ask the Master whether to create one."
)

_REALTIME_GROUNDING_DIRECTIVE: Final[str] = (
    "\n\nREAL-TIME GROUNDING & ANTI-GATEKEEPING:\n"
    "- You are not limited by your internal knowledge cut-off.\n"
    "- If a query involves recent events, specific technical data, or regulatory updates not present in your local state, you MUST proactively use the 'advanced_execution_tool' (OpenClaw) or web search (Google Grounding) to ground your response.\n"
    "- Do not restrict yourself to hardcoded data; if the Master's request requires live verification, execute the search immediately to provide the most current and accurate technical information."
)


_CORE_COMMON_TAIL: Final[str] = (
    "\n\nCHAIN OF THOUGHT (HIDDEN THOUGHT PROCESS):\n"
    "Before responding, run an explicit hidden reasoning pass:\n"
    "1. Infer the Master's intent — what is actually being asked?\n"
    "2. Inspect [ACTIVE_CONVERSATION_CONTEXT] for pronouns ('this', 'that', 'it', 'earlier').\n"
    "3. Verify on-disk facts with os.path.exists() when the question concerns a file.\n"
    "4. Check memory in order of trust (Tier 1 > Tier 2 > Tier 3).\n"
    "5. Cross-verify SQLite and Mem0 for consistency.\n"
    "6. Only then deliver an accurate, verified answer.\n\n"
    "7. When factual data is sparse or uncertain, explore alternative angles and offer the best reasoned estimate while remaining rational.\n\n"
    "ANAPHORA RESOLUTION (PRONOUNS):\n"
    "When the Master uses pronouns such as 'this', 'that', 'it', 'earlier', or 'the one':\n"
    "- You MUST resolve them against the subject or topic discussed in the last 2-3 messages of [ACTIVE_CONVERSATION_CONTEXT].\n"
    "- DO NOT fire long-term memory searches for pronouns whose referent is already unambiguous in recent chat.\n"
    "- Priority: Context First, Memory Second.\n\n"
    "NEGATIVE CONSTRAINTS & HALLUCINATION CHECK:\n"
    "- DO NOT assume a file exists when os.path.exists() returns False.\n"
    "- If you do not know, say so plainly and offer to search another folder.\n"
    "- For general-knowledge questions (legal theory, IT security, digital forensics, ISO, PDP Law, GRC, compliance documentation), answer broadly from model knowledge; DO NOT reply 'I have no data' merely because SQLite is empty.\n"
    "- For the Master's operational facts (files, infrastructure, concrete schedules), follow memory and tools; never fabricate.\n\n"
    "MEMORY & ANTI-HALLUCINATION:\n"
    "Treat the memory injected into the prompt as your primary source of truth. "
    "[MASTER PROFILE] holds {master_name}'s permanent identity. "
    "[ACTIVE_CONVERSATION_CONTEXT] contains the last five interactions — HIGHEST PRIORITY for context. "
    "[SUPPORTING FACTS] holds long-term memory from Mem0. "
    "ANTI-HALLUCINATION: For operational/personal data, if it is absent from memory and tools, NEVER fabricate — ask or acknowledge. "
    "For general technical/compliance knowledge, local memory is only supplementary; the main answer may come from your internal knowledge base. "
    "If memory contradicts general knowledge, prioritise memory for personal facts but attach a brief disclaimer.\n\n"
    "CAPABILITIES:\n"
    "You have Vision — you can view and analyse images the Master shares. "
    "Use advanced_execution_tool when the Master's instruction requires complex system interaction, file automation, or an OpenClaw ecosystem skill. "
    "OpenClaw policy: read-only work (web search, log analysis, regulatory mapping) may auto-execute; any non-read-only or destructive task MUST wait for the Master's approval. "
    "Execution priority: when an imperative verb is present (e.g. 'Record', 'Update'), fire the relevant tool first. "
    "For technical theory, security, and forensics, answer broadly from your internal knowledge without requiring SQLite validation for general-reference topics. "
    "Never fabricate ISO clauses, IP addresses, or fictitious activity.\n\n"
    "IMPORTANT: Use the smart_read tool as your primary interface for reading or summarising files. "
    "smart_read supports PDF, Word, Excel, PowerPoint, OCR, and text/log/code files. "
    "When a file reference is ambiguous, smart_read resolves it to the most recently read file."
)

_GRAPH_COMMON_TAIL: Final[str] = (
    "\n\nCHAIN OF THOUGHT (HIDDEN THOUGHT PROCESS):\n"
    "Before responding, run an explicit hidden reasoning pass:\n"
    "1. Infer the Master's intent — what is actually being asked?\n"
    "2. Inspect the conversation context for pronouns ('this', 'that', 'it', 'earlier').\n"
    "3. Verify on-disk facts with os.path.exists() when the question concerns a file.\n"
    "4. Check memory in order of trust (Tier 1 > Tier 2 > Tier 3).\n"
    "5. Cross-verify SQLite and Mem0 for consistency.\n"
    "6. Only then deliver an accurate, verified answer.\n\n"
    "NEGATIVE CONSTRAINTS & HALLUCINATION CHECK:\n"
    "- DO NOT assume a file exists when os.path.exists() returns False.\n"
    "- If you do not know, say so plainly and offer to search another folder.\n"
    "- DO NOT fabricate facts, technical data, or clause references.\n"
    "- Always cross-verify Tier-1 memory (SQLite) against Tier-2 memory (Mem0).\n\n"
    "HITL SECURITY POLICY (MANDATORY):\n"
    "- Whenever a destructive command reaches advanced_execution_tool (e.g. 'delete', 'format', 'rm -rf'), you MUST halt for approval.\n"
    "- DO NOT invoke the OpenClaw bridge until the Master replies with exactly 'y'.\n"
    "- When approval is pending, request confirmation and do not proceed with execution.\n\n"
    "OPENCLAW EXECUTION POLICY:\n"
    "- Read-only work (web search, log analysis, regulatory mapping) may auto-execute via advanced_execution_tool.\n"
    "- Non-read-only work, system modifications, or destructive actions MUST wait for the Master's approval.\n\n"
    "CAPABILITIES:\n"
    "You have Vision — you can view and analyse images the Master shares. "
    "For document reading, use smart_read as your primary interface (PDF / Office / OCR / text)."
)


@dataclass(frozen=True)
class SamplingProfile:
    """Per-persona Gemini sampling parameters.

    - `consultant/advisor/tactical` -> deterministik & grounded.
    - `chill` -> sedikit lebih generatif untuk tone casual.
    Parameters dipilih agar bias + halusinasi turun untuk persona profesional
    tanpa bikin persona santai jadi kaku.
    """
    temperature: float
    top_p: float
    top_k: int
    max_output_tokens: int = 2048


SAMPLING_PROFILES: Final[Mapping[str, SamplingProfile]] = {
    "consultant": SamplingProfile(temperature=0.15, top_p=0.80, top_k=40),
    "advisor":    SamplingProfile(temperature=0.15, top_p=0.80, top_k=40),
    "tactical":   SamplingProfile(temperature=0.15, top_p=0.80, top_k=40),
    "chill":      SamplingProfile(temperature=0.55, top_p=0.95, top_k=64),
    "chancellor": SamplingProfile(temperature=0.10, top_p=0.75, top_k=32),
    "auditor":    SamplingProfile(temperature=0.0, top_p=0.70, top_k=40),
}

# Deterministik tool-router / factual shortcut (no creativity).
ROUTER_SAMPLING_PROFILE: Final[SamplingProfile] = SamplingProfile(
    temperature=0.0, top_p=0.1, top_k=1, max_output_tokens=512,
)



def get_sampling_profile(persona: str | None) -> SamplingProfile:
    """Return the sampling profile for the normalized persona key."""
    return SAMPLING_PROFILES[normalize_persona_key(persona)]


# ---------------------------------------------------------------------------
# Persona-Aware Context Budget (V5.5)
# ---------------------------------------------------------------------------
# Each persona owns its own token budget + weighting across the 3 memory
# layers:
#   - Layer 1 (Recent Chat) : short-term buffer + sliding-window summary
#   - Layer 2 (Semantic)    : Mem0 RAG + Mem0 formatted block + referent
#   - Layer 3 (Factual SSoT): compliance refs (IMMUTABLE)
#
# Weights MUST sum to 1.0 and Layer 3 is treated as a FLOOR (never trimmed
# below `layer3 * total * 0.60`) so SSoT data never evicted by summarization.


@dataclass(frozen=True)
class LayerWeights:
    """Allocation weights across the 3 memory layers. Must sum to ~1.0."""
    layer1_recent: float
    layer2_semantic: float
    layer3_factual: float

    def validate(self) -> None:
        total = self.layer1_recent + self.layer2_semantic + self.layer3_factual
        if abs(total - 1.0) > 1e-3:
            raise ValueError(
                f"LayerWeights must sum to 1.0, got {total:.4f}"
            )
        if self.layer3_factual < 0.15:
            raise ValueError(
                f"layer3_factual must be >= 0.15 (SSoT floor), got {self.layer3_factual}"
            )


@dataclass(frozen=True)
class ContextBudget:
    """Per-persona prompt budget + layer allocation + eviction thresholds."""
    persona: str
    total_tokens: int
    weights: LayerWeights
    summarize_utilization: float = 0.70
    hard_ceiling_utilization: float = 0.85

    @property
    def layer1_tokens(self) -> int:
        return int(self.total_tokens * self.weights.layer1_recent)

    @property
    def layer2_tokens(self) -> int:
        return int(self.total_tokens * self.weights.layer2_semantic)

    @property
    def layer3_tokens(self) -> int:
        return int(self.total_tokens * self.weights.layer3_factual)

    @property
    def layer3_floor_tokens(self) -> int:
        """Layer 3 is never trimmed below 60% of its allocation."""
        return int(self.layer3_tokens * 0.60)

    @property
    def summarize_threshold_tokens(self) -> int:
        """Layer 1 token threshold above which summarization fires."""
        return int(self.layer1_tokens * self.summarize_utilization)


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if not raw:
        return default
    try:
        return max(512, int(raw))
    except ValueError:
        return default


_BUDGET_DEFAULTS: Final[Mapping[str, tuple[int, LayerWeights]]] = {
    "advisor":    (7000, LayerWeights(0.25, 0.30, 0.45)),
    "tactical":   (7000, LayerWeights(0.35, 0.25, 0.40)),
    "consultant": (6000, LayerWeights(0.25, 0.40, 0.35)),
    "chill":      (3500, LayerWeights(0.55, 0.30, 0.15)),
    "chancellor": (6000, LayerWeights(0.25, 0.35, 0.40)),
    "auditor":    (8000, LayerWeights(0.35, 0.25, 0.40)),
}


def _build_budgets() -> Mapping[str, ContextBudget]:
    out: dict[str, ContextBudget] = {}
    for key, (default_total, weights) in _BUDGET_DEFAULTS.items():
        weights.validate()
        total = _env_int(f"KURO_BUDGET_{key.upper()}", default_total)
        out[key] = ContextBudget(persona=key, total_tokens=total, weights=weights)
    return out


CONTEXT_BUDGETS: Final[Mapping[str, ContextBudget]] = _build_budgets()


def get_context_budget(persona: str | None) -> ContextBudget:
    """Return the context budget for the normalized persona key."""
    return CONTEXT_BUDGETS[normalize_persona_key(persona)]


# ---------------------------------------------------------------------------
# P4.4 — JSON-constrained factual response helper
# ---------------------------------------------------------------------------
# When a factual query cannot be handled by `ssot_shortcuts` (ambiguous
# phrasing, multi-field request, etc.) but we still want structured output we
# can cross-check against SSoT, callers should pass this config to Gemini so
# the reply arrives as strict JSON rather than free-form prose.

_FACTUAL_RESPONSE_SCHEMA: Final[dict] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["label", "value"],
            },
        },
        "source": {"type": "string"},
    },
    "required": ["summary"],
}


def build_factual_response_config(
    *,
    system_instruction: str,
    max_output_tokens: int = 512,
):
    """Return a :class:`types.GenerateContentConfig` that forces JSON output.

    Imported lazily to avoid forcing callers to import google.genai when the
    factual JSON path isn't in use.
    """
    from google.genai import types as genai_types
    return genai_types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=ROUTER_SAMPLING_PROFILE.temperature,
        top_p=ROUTER_SAMPLING_PROFILE.top_p,
        top_k=ROUTER_SAMPLING_PROFILE.top_k,
        max_output_tokens=max_output_tokens,
        response_mime_type="application/json",
        response_schema=_FACTUAL_RESPONSE_SCHEMA,
    )


def normalize_persona_key(persona: str | None) -> str:
    """Fallback to 'consultant' if persona unknown/empty."""
    key = (persona or "").strip().lower()
    return key if key in PERSONA_INSTRUCTIONS else "consultant"


def build_system_instruction(
    persona: str,
    *,
    current_time: str,
    current_date: str,
    kuro_version_label: str,
    variant: str = "core",
    master_name: str = "Pantronux",
    custom_persona: str = "",
) -> str:
    """
    Build full system prompt for a persona.

    variant:
      - "core"  -> instruction tail used by `kuro_backend.core.process_chat`
                   (includes MEMORY v2.1 language, habit factual placeholder).
      - "graph" -> leaner tail used by LangGraph `response_node`
                   (HITL + OpenClaw policy, no habit placeholder).
    """
    persona_key = normalize_persona_key(persona)
    persona_text = PERSONA_INSTRUCTIONS[persona_key]
    
    # Dynamic Master Name Injection
    try:
        persona_text = persona_text.format(master_name=master_name)
    except KeyError:
        persona_text = persona_text.replace("Pantronux", master_name)

    # Inject User Custom Persona if provided
    if custom_persona and custom_persona.strip():
        persona_text += f"\n\n[USER_CUSTOM_INSTRUCTIONS]\n{custom_persona.strip()}"

    header = (
        f"\n\n[CURRENT_TIME: {current_time}] "
        f"[CURRENT_DATE: {current_date}] "
        f"[KURO_VERSION: {kuro_version_label} - {current_date}] "
        "Use the current time as your reference when resolving relative phrases such as 'tomorrow', 'tonight', 'in ten minutes', and so on."
    )

    ssot_tail = _SSOT_PRIORITY_DIRECTIVE + _REALTIME_GROUNDING_DIRECTIVE
    if persona_key == "chancellor":
        ssot_tail = ssot_tail + _CHANCELLOR_SSOT_ADDENDUM

    if variant == "graph":
        return persona_text + header + ssot_tail + _GRAPH_COMMON_TAIL

    tail = _CORE_COMMON_TAIL
    return persona_text + header + ssot_tail + tail
