"""QA runtime orchestration entrypoint."""

# --- Header Doc ---
# Purpose: Orchestrate QA requirement parsing, testcase generation, and gherkin output.
# Caller: main.py QA playground routes.
# Dependencies: runtime_context.py, memory_v2.memory_store.py, QA modules.
# Main Functions: interpret(), generate_testcases(), generate_gherkin(), process_request().
# Side Effects: Stores episodic QA runtime memory into `kuro.qa` namespace.

from __future__ import annotations

import logging
from typing import Any

from kuro_backend.memory_v2.memory_store import KuroMemory, MemoryStore
from kuro_backend.output.schema_registry import QAOutputV1, TestCase
from kuro_backend.playground.qa.cucumber_generator import generate_gherkin
from kuro_backend.playground.qa.requirement_parser import parse_requirements
from kuro_backend.playground.qa.testcase_generator import generate_testcases
from kuro_backend.runtime.boundary_guard import BoundaryViolationError, assert_memory_access
from kuro_backend.runtime.runtime_context import RuntimeContext, resolve_runtime_context

logger = logging.getLogger(__name__)


class QARuntime:
    def __init__(self, username: str, chat_id: str, runtime_id: str = "qa"):
        self.username = username
        self.chat_id = chat_id
        self.ctx: RuntimeContext = resolve_runtime_context(
            runtime_id=runtime_id,
            username=username,
            chat_id=chat_id,
        )
        self.store = MemoryStore()

    def _store_episodic(self, content: str, source: str = "qa_playground") -> None:
        if not content:
            return
        try:
            assert_memory_access(self.ctx, self.ctx.memory_namespace)
            memory = KuroMemory(
                runtime_id=self.ctx.runtime_id,
                namespace=self.ctx.memory_namespace,
                type="episodic",
                content=content.strip()[:2000],
                source=source,
                username=self.username,
            )
            self.store.add(memory)
        except BoundaryViolationError as exc:
            logger.warning("[QA_RUNTIME] boundary block on episodic store: %s", exc)
        except Exception as exc:
            logger.warning("[QA_RUNTIME] episodic memory write skipped: %s", exc)

    @staticmethod
    def _normalize_testcases(raw_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in raw_cases:
            if not isinstance(item, dict):
                continue
            try:
                normalized.append(TestCase(**item).model_dump())
            except Exception:
                continue
        return normalized

    async def interpret(self, requirement: str) -> dict[str, Any]:
        parsed = await parse_requirements(requirement, self.ctx)
        self._store_episodic(
            f"Requirement interpreted: {parsed.get('main_functionality', '')}",
            source="qa_interpret",
        )
        return parsed

    async def generate_testcases(self, requirement: str) -> dict[str, Any]:
        parsed = await parse_requirements(requirement, self.ctx)
        raw_cases = await generate_testcases(parsed, self.ctx)
        normalized_cases = self._normalize_testcases(raw_cases)
        payload = QAOutputV1(
            task_type="testcase_generation",
            input_summary=str(parsed.get("main_functionality", requirement)),
            assumptions=list(parsed.get("constraints", []) or []),
            test_cases=normalized_cases,
            risks=list(parsed.get("edge_cases", []) or []),
            confidence_score=0.7 if normalized_cases else 0.3,
        )
        self._store_episodic(
            f"Generated {len(normalized_cases)} QA test cases",
            source="qa_testcase_generation",
        )
        return payload.model_dump()

    async def generate_gherkin(self, requirement: str) -> dict[str, Any]:
        parsed = await parse_requirements(requirement, self.ctx)
        gherkin = await generate_gherkin(parsed, self.ctx)
        self._store_episodic("Generated gherkin scenario", source="qa_gherkin_generation")
        return {
            "runtime": "qa",
            "task_type": "gherkin_generation",
            "gherkin": gherkin,
            "schema_version": "qa_output_v1",
        }

    async def process_request(self, action: str, requirement: str) -> dict[str, Any]:
        """
        Runtime wrapper with safe fallback.
        Never raises; returns structured success/error envelope.
        """
        try:
            if action == "interpret":
                return {"ok": True, "data": await self.interpret(requirement)}
            if action == "generate_testcases":
                return {"ok": True, "data": await self.generate_testcases(requirement)}
            if action == "generate_gherkin":
                return {"ok": True, "data": await self.generate_gherkin(requirement)}
            return {"ok": False, "error": f"Unknown action: {action}"}
        except BoundaryViolationError as exc:
            logger.warning("[QA_RUNTIME] boundary violation: %s", exc)
            return {"ok": False, "error": f"Boundary violation: {exc}"}
        except Exception as exc:
            logger.error("[QA_RUNTIME] request failed: %s", exc)
            return {"ok": False, "error": str(exc)}
