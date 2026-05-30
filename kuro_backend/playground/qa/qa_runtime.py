"""QA runtime orchestration entrypoint."""

# --- Header Doc ---
# Purpose: Orchestrate QA requirement parsing, testcase generation, and gherkin output.
# Caller: main.py QA playground routes.
# Dependencies: runtime_context.py, memory_v2.memory_store.py, QA modules.
# Main Functions: interpret(), generate_testcases(), generate_gherkin(), process_request().
# Side Effects: Stores episodic QA runtime memory into `kuro.qa` namespace.

from __future__ import annotations

import logging
import re
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

    @staticmethod
    def _text_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @staticmethod
    def _case_search_text(testcase: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ("id", "title", "precondition", "expected_result", "priority", "type"):
            value = testcase.get(key)
            if value:
                parts.append(str(value))
        for step in testcase.get("steps", []) or []:
            if isinstance(step, dict):
                parts.extend(
                    str(step.get(key, ""))
                    for key in ("action", "expected_result")
                    if step.get(key)
                )
        return " ".join(parts).lower()

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

    async def analyze_ambiguity(self, requirement: str) -> dict[str, Any]:
        parsed = await parse_requirements(requirement, self.ctx)
        raw_requirement = str(parsed.get("raw_requirement") or requirement or "").strip()
        criteria = self._text_list(parsed.get("acceptance_criteria"))
        constraints = self._text_list(parsed.get("constraints"))
        edge_cases = self._text_list(parsed.get("edge_cases"))
        ambiguities: list[dict[str, Any]] = []
        missing_information: list[str] = []

        if len(raw_requirement.split()) < 8:
            ambiguities.append(
                {
                    "id": "AMB-001",
                    "severity": "medium",
                    "field": "raw_requirement",
                    "issue": "Requirement is very short.",
                    "recommendation": "Add actor, trigger, expected outcome, and failure behavior.",
                }
            )
        if not criteria:
            missing_information.append("acceptance_criteria")
            ambiguities.append(
                {
                    "id": "AMB-002",
                    "severity": "high",
                    "field": "acceptance_criteria",
                    "issue": "No explicit acceptance criteria were parsed.",
                    "recommendation": "Define observable pass/fail criteria before implementation.",
                }
            )
        if not edge_cases:
            missing_information.append("edge_cases")
        vague_terms = [
            term
            for term in ("fast", "easy", "secure", "robust", "intuitive", "soon")
            if re.search(rf"\b{re.escape(term)}\b", raw_requirement.lower())
        ]
        if vague_terms:
            ambiguities.append(
                {
                    "id": "AMB-003",
                    "severity": "medium",
                    "field": "wording",
                    "issue": f"Vague quality terms detected: {', '.join(vague_terms)}.",
                    "recommendation": "Replace vague terms with measurable thresholds or examples.",
                }
            )

        self._store_episodic(
            f"Analyzed QA ambiguity: {len(ambiguities)} findings",
            source="qa_ambiguity_analysis",
        )
        return {
            "runtime": "qa",
            "task_type": "ambiguity_analysis",
            "schema_version": "qa_productization_v1",
            "input_summary": str(parsed.get("main_functionality") or raw_requirement),
            "ambiguities": ambiguities,
            "missing_information": missing_information,
            "assumptions": constraints,
            "risks": edge_cases,
            "confidence_score": 0.72 if not ambiguities else 0.48,
        }

    async def coverage_matrix(self, requirement: str) -> dict[str, Any]:
        parsed = await parse_requirements(requirement, self.ctx)
        criteria = self._text_list(parsed.get("acceptance_criteria"))
        if not criteria:
            summary = str(parsed.get("main_functionality") or requirement).strip()
            criteria = [summary] if summary else []
        raw_cases = await generate_testcases(parsed, self.ctx)
        test_cases = self._normalize_testcases(raw_cases)
        matrix: list[dict[str, Any]] = []
        stopwords = {"the", "and", "or", "to", "a", "an", "of", "in", "with", "for"}

        for index, criterion in enumerate(criteria, start=1):
            tokens = {
                token
                for token in re.findall(r"[a-z0-9]+", criterion.lower())
                if token not in stopwords and len(token) > 2
            }
            covered_by: list[str] = []
            for testcase in test_cases:
                haystack = self._case_search_text(testcase)
                if not tokens or any(token in haystack for token in tokens):
                    covered_by.append(str(testcase.get("id") or testcase.get("title") or "unnamed"))
            matrix.append(
                {
                    "requirement_id": f"REQ-{index:03d}",
                    "description": criterion,
                    "covered_by": covered_by,
                    "coverage": "covered" if covered_by else "missing",
                }
            )

        gaps = [item for item in matrix if item["coverage"] == "missing"]
        self._store_episodic(
            f"Built QA coverage matrix: {len(matrix)} requirements, {len(gaps)} gaps",
            source="qa_coverage_matrix",
        )
        return {
            "runtime": "qa",
            "task_type": "coverage_matrix",
            "schema_version": "qa_productization_v1",
            "requirements": matrix,
            "test_case_count": len(test_cases),
            "coverage_gaps": gaps,
            "confidence_score": 0.74 if test_cases else 0.35,
        }

    async def export_bundle(self, requirement: str, export_format: str = "json") -> dict[str, Any]:
        parsed = await parse_requirements(requirement, self.ctx)
        raw_cases = await generate_testcases(parsed, self.ctx)
        test_cases = self._normalize_testcases(raw_cases)
        gherkin = await generate_gherkin(parsed, self.ctx)
        normalized_format = (export_format or "json").strip().lower()
        if normalized_format not in {"json", "markdown", "gherkin"}:
            normalized_format = "json"

        artifact: dict[str, Any] = {
            "requirement": parsed,
            "test_cases": test_cases,
            "gherkin": gherkin,
        }
        if normalized_format == "markdown":
            artifact["markdown"] = (
                f"# QA Playground Export\n\n"
                f"## Requirement\n{parsed.get('main_functionality', '')}\n\n"
                f"## Test Cases\n{len(test_cases)} generated\n\n"
                f"## Gherkin\n```gherkin\n{gherkin}\n```"
            )
        elif normalized_format == "gherkin":
            artifact = {"gherkin": gherkin}

        self._store_episodic(
            f"Prepared QA export bundle as {normalized_format}",
            source="qa_export_bundle",
        )
        return {
            "runtime": "qa",
            "task_type": "qa_export",
            "schema_version": "qa_export_plan_v1",
            "export_status": "prepared",
            "format": normalized_format,
            "filename_suggestion": f"qa_playground_export.{normalized_format}",
            "supported_formats": ["json", "markdown", "gherkin"],
            "artifact": artifact,
        }

    async def process_request(
        self,
        action: str,
        requirement: str,
        **options: Any,
    ) -> dict[str, Any]:
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
            if action == "analyze_ambiguity":
                return {"ok": True, "data": await self.analyze_ambiguity(requirement)}
            if action == "coverage_matrix":
                return {"ok": True, "data": await self.coverage_matrix(requirement)}
            if action == "export_bundle":
                return {
                    "ok": True,
                    "data": await self.export_bundle(
                        requirement,
                        export_format=str(options.get("format") or "json"),
                    ),
                }
            return {"ok": False, "error": f"Unknown action: {action}"}
        except BoundaryViolationError as exc:
            logger.warning("[QA_RUNTIME] boundary violation: %s", exc)
            return {"ok": False, "error": f"Boundary violation: {exc}"}
        except Exception as exc:
            logger.error("[QA_RUNTIME] request failed: %s", exc)
            return {"ok": False, "error": str(exc)}
