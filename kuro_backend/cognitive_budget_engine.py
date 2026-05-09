from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class CognitiveBudget:
    max_reflection_depth: int
    max_consensus_rounds: int
    max_retrieval_expansion: int
    max_tool_calls: int


DEFAULT_BUDGET = CognitiveBudget(
    max_reflection_depth=int(os.getenv("KURO_CANVAS3_MAX_REFLECTION_DEPTH", "2")),
    max_consensus_rounds=int(os.getenv("KURO_CANVAS3_MAX_CONSENSUS_ROUNDS", "3")),
    max_retrieval_expansion=int(os.getenv("KURO_CANVAS3_MAX_RETRIEVAL_EXPANSION", "5")),
    max_tool_calls=int(os.getenv("KURO_CANVAS3_MAX_TOOL_CALLS", "4")),
)


def evaluate_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    trace: List[str] = []
    retrieval_retry = int(state.get("retrieval_retry_count", 0) or 0)
    blocked = False

    if retrieval_retry > DEFAULT_BUDGET.max_retrieval_expansion:
        blocked = True
        trace.append("retrieval_expansion_limit_exceeded")

    return {
        "limits": {
            "max_reflection_depth": DEFAULT_BUDGET.max_reflection_depth,
            "max_consensus_rounds": DEFAULT_BUDGET.max_consensus_rounds,
            "max_retrieval_expansion": DEFAULT_BUDGET.max_retrieval_expansion,
            "max_tool_calls": DEFAULT_BUDGET.max_tool_calls,
        },
        "blocked": blocked,
        "budget_enforcement_trace": trace,
        "degradation_mode": "compact_reasoning" if blocked else "normal",
    }
