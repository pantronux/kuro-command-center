"""
Kuro AI V4.0 - Guardrails Orchestrator
================================================================================
Unified validation orchestrator that runs all guardrails and handles re-ask loops.
"""
import logging
import os
import logging.handlers
from typing import Dict, List, Optional, Any
from datetime import datetime

from kuro_backend.guardrails.schemas import GuardrailResult, ValidationFailure
from kuro_backend.guardrails.compliance_guard import ComplianceGuardrail
from kuro_backend.guardrails.privacy_guard import PrivacyGuardrail
from kuro_backend.guardrails.tone_guard import ToneGuardrail

logger = logging.getLogger(__name__)

# Separate guardrails logger with dedicated file handler
_guardrails_logger = None

def get_guardrails_logger() -> logging.Logger:
    """Get or create the dedicated guardrails logger."""
    global _guardrails_logger
    if _guardrails_logger is None:
        _guardrails_logger = logging.getLogger("kuro_guardrails")
        _guardrails_logger.setLevel(logging.INFO)
        
        # Guardrails log file
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "guardrails.log")
        
        # TimedRotatingFileHandler for guardrails log
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_file,
            when='midnight',
            interval=1,
            backupCount=14,  # Keep 14 days of guardrails logs
            encoding='utf-8'
        )
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        _guardrails_logger.addHandler(file_handler)
        
        # Also add console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s - [GUARDRAILS] %(levelname)s - %(message)s'
        ))
        _guardrails_logger.addHandler(console_handler)
    
    return _guardrails_logger


class GuardrailsOrchestrator:
    """
    Orchestrates all guardrails validation for Kuro responses.
    
    Flow:
    1. Run Compliance Guardrail (if compliance query)
    2. Run Privacy Guardrail (always)
    3. Run Tone Guardrail (if scolding/evaluation)
    4. Aggregate results and determine if re-ask is needed
    """
    
    def __init__(self):
        self.compliance_guard = ComplianceGuardrail()
        self.privacy_guard = PrivacyGuardrail()
        self.tone_guard = ToneGuardrail()
        self.gr_logger = get_guardrails_logger()
        
        # Max re-ask attempts before fallback
        self.max_reasks = 2
    
    def validate_response(
        self,
        response_text: str,
        user_query: str,
        compliance_data: List[Dict] = None,
        is_scolding: bool = False,
        habit_data: Dict = None
    ) -> GuardrailResult:
        """
        Run all applicable guardrails on a response.
        
        Args:
            response_text: The generated response
            user_query: Original user query
            compliance_data: Compliance search results (if any)
            is_scolding: Whether this is a scolding response
            habit_data: Habit data (if any)
            
        Returns:
            GuardrailResult with aggregated validation status
        """
        all_failures = []
        
        # Determine query type
        is_compliance_query = self._is_compliance_query(user_query)
        
        # 1. Compliance Guardrail (if applicable)
        if is_compliance_query:
            self.gr_logger.info(f"[ORCHESTRATOR] Running compliance guardrail for query: {user_query[:60]}...")
            compliance_result = self.compliance_guard.validate(
                response_text=response_text,
                compliance_data=compliance_data,
                user_query=user_query
            )
            all_failures.extend(compliance_result.failures)
        
        # 2. Privacy Guardrail (always runs)
        self.gr_logger.info(f"[ORCHESTRATOR] Running privacy guardrail")
        privacy_result = self.privacy_guard.validate(
            response_text=response_text,
            user_query=user_query
        )
        all_failures.extend(privacy_result.failures)
        
        # 3. Tone Guardrail (if scolding)
        if is_scolding:
            self.gr_logger.info(f"[ORCHESTRATOR] Running tone guardrail for scolding")
            tone_result = self.tone_guard.validate(
                response_text=response_text,
                user_query=user_query,
                is_scolding=True
            )
            all_failures.extend(tone_result.failures)
        
        # Aggregate results
        critical_count = sum(1 for f in all_failures if f.severity == "critical")
        warning_count = sum(1 for f in all_failures if f.severity == "warning")
        is_valid = critical_count == 0
        
        result = GuardrailResult(
            is_valid=is_valid,
            failures=all_failures
        )
        
        # Log summary
        self.gr_logger.info(
            f"[ORCHESTRATOR] Validation complete: "
            f"valid={is_valid}, critical={critical_count}, warnings={warning_count}, "
            f"total_failures={len(all_failures)}"
        )
        
        if not is_valid:
            self.gr_logger.warning(
                f"[ORCHESTRATOR] GUARDRAIL VIOLATION DETECTED | "
                f"Query: {user_query[:100]} | "
                f"Failures: {result.failure_summary}"
            )
        
        return result
    
    def generate_reask_prompt(
        self,
        original_query: str,
        original_response: str,
        failures: List[ValidationFailure]
    ) -> str:
        """
        Generate a re-ask prompt that instructs the LLM to fix the violations.
        
        Args:
            original_query: The original user query
            original_response: The response that failed validation
            failures: List of validation failures
            
        Returns:
            New prompt for re-generation
        """
        reask_instructions = []
        
        for failure in failures:
            if failure.severity == "critical":
                reask_instructions.append(
                    f"- PERBAIKAN KRITIS ({failure.guardrail_type}): {failure.detail}\n"
                    f"  Saran: {failure.suggestion}"
                )
            else:
                reask_instructions.append(
                    f"- PERBAIKAN WARNING ({failure.guardrail_type}): {failure.detail}\n"
                    f"  Saran: {failure.suggestion}"
                )
        
        instructions_text = "\n".join(reask_instructions)
        
        reask_prompt = f"""PERINGATAN GUARDRAIL: Respons sebelumnya gagal validasi.

QUERY ASLI: {original_query}

RESPONS SEBELUMNYA (GAGAL VALIDASI):
{original_response}

PERBAIKAN YANG DIPERLUKAN:
{instructions_text}

TUGAS: Buat ulang respons yang memenuhi SEMUA aturan guardrail di atas.
Pastikan:
1. Semua referensi ISO/klausul valid dan ada dalam dokumen sumber
2. Tidak ada data PII (email, IP, password, dll) yang bocor
3. Tidak ada kata kunci rahasia proyek yang terungkap
4. Jika ini adalah evaluasi habit, sertakan dampak logis dan motivasi
5. Jaga nada profesional sebagai mentor

RESPONS BARU:"""
        
        return reask_prompt
    
    def _is_compliance_query(self, query: str) -> bool:
        """Determine if a query is compliance-related."""
        compliance_keywords = [
            "iso", "iso 27001", "iso 27002", "nist", "gdpr", "audit", "compliance",
            "kontrol", "control", "klausul", "clause", "annex", "lampiran",
            "sertifikasi", "certification", "risk assessment", "isms", "pims",
            "togaf", "business continuity", "a.5", "a.6", "a.7", "a.8",
            "iso 27701", "iso 42001", "csf", "800-53", "uu pdp"
        ]
        query_lower = query.lower()
        return any(kw in query_lower for kw in compliance_keywords)
