"""
Kuro AI V4.0 - Privacy Guardrail
================================================================================
Validator for privacy/security:
1. PII Filter: Detects and blocks email, IP, password, phone leaks
2. Medco Confidentiality: Detects sensitive project keywords
"""
import logging
import re
from typing import List, Optional
from kuro_backend.guardrails.schemas import GuardrailResult, ValidationFailure, PrivacyCheckResult

logger = logging.getLogger(__name__)

# PII Detection Patterns
PII_PATTERNS = {
    "email": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    "ipv4": re.compile(r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'),
    "ipv6": re.compile(r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b'),
    "password": re.compile(r'(?:password|passwd|pwd)\s*[:=]\s*\S+', re.IGNORECASE),
    "phone_indonesia": re.compile(r'\b(?:\+62|62|0)[0-9]{9,13}\b'),
    "nik_ktp": re.compile(r'\b\d{16}\b'),  # Indonesian NIK (16 digits)
    "credit_card": re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),
    "api_key": re.compile(r'(?:api[_-]?key|apikey|secret[_-]?key)\s*[:=]\s*[A-Za-z0-9]{16,}', re.IGNORECASE),
}

# Medco Confidentiality Keywords
# These are project-specific terms that should not leak in general chat
MEDCO_CONFIDENTIAL_KEYWORDS = [
    "medco internal",
    "medco confidential",
    "medco secret",
    "gap analysis medco",
    "audit medco",
    "penilaian risiko medco",
    "dokumen internal medco",
    "medco employee",
    "medco staff list",
    "medco salary",
    "medco budget",
    "medco contract",
    "medco vendor list",
    "medco password",
    "medco credential",
    "medco access key",
]

# General sensitive patterns
SENSITIVE_CONTEXT_KEYWORDS = [
    "rahasia perusahaan",
    "confidential document",
    "internal memo",
    "not for distribution",
    "restricted access",
]


class PrivacyGuardrail:
    """
    Validates responses for privacy violations and data leaks.
    
    Rules:
    1. PII Filter: Block email, IP, password, phone, NIK, credit card, API keys
    2. Medco Confidentiality: Block sensitive project keywords
    3. Context-Aware: Allow PII if discussing security concepts (not real data)
    """
    
    def __init__(self):
        self.name = "privacy_guardrail"
    
    def validate(
        self,
        response_text: str,
        user_query: str = ""
    ) -> GuardrailResult:
        """
        Validate a response for privacy violations.
        
        Args:
            response_text: The generated response text
            user_query: Original user query
            
        Returns:
            GuardrailResult with validation status
        """
        failures = []
        
        # Check 1: PII Detection
        pii_result = self._check_pii(response_text)
        if not pii_result.is_safe:
            for pii_type in pii_result.pii_types_found:
                failures.append(ValidationFailure(
                    guardrail_type="privacy",
                    rule_violated=f"pii_detected_{pii_type}",
                    severity="critical",
                    detail=f"Terdeteksi kebocoran data PII tipe '{pii_type}' dalam respons.",
                    suggestion=f"Hapus atau redaksi semua data {pii_type} dari respons. Jangan pernah menampilkan data pribadi nyata."
                ))
        
        # Check 2: Medco Confidentiality
        confidentiality_result = self._check_medco_confidentiality(response_text)
        if confidentiality_result.has_confidential_project_data:
            for kw in confidentiality_result.confidential_keywords_found:
                failures.append(ValidationFailure(
                    guardrail_type="privacy",
                    rule_violated="confidential_project_data",
                    severity="critical",
                    detail=f"Terdeteksi kata kunci rahasia proyek: '{kw}'.",
                    suggestion="Jangan membahas detail internal proyek klien. Gunakan referensi umum tanpa nama."
                ))
        
        is_valid = len([f for f in failures if f.severity == "critical"]) == 0
        
        result = GuardrailResult(
            is_valid=is_valid,
            failures=failures
        )
        
        if not is_valid:
            logger.warning(
                f"[PRIVACY_GUARDRAIL] Validation failed: {result.failure_summary} | "
                f"Query: {user_query[:80]}..."
            )
        else:
            logger.info(f"[PRIVACY_GUARDRAIL] Validation passed for query: {user_query[:50]}...")
        
        return result
    
    def _check_pii(self, text: str) -> PrivacyCheckResult:
        """Check for PII patterns in text with context awareness."""
        result = PrivacyCheckResult()
        pii_found = []
        
        # Context-aware: skip IP detection if it's part of infrastructure description
        # (e.g., "Host di 192.168.18.216" is infrastructure context, not a leak)
        infrastructure_context = re.search(r'(?:host|server|vm|ip address|gateway|dns|subnet)\s+(?:di|pada|adalah|:)?\s*\d', text, re.IGNORECASE)
        
        for pii_type, pattern in PII_PATTERNS.items():
            # Skip IP detection if in infrastructure context
            if pii_type in ('ipv4', 'ipv6') and infrastructure_context:
                continue
            # Skip email if it's a generic example
            if pii_type == 'email' and re.search(r'example\.com|contoh\.com|test@test', text, re.IGNORECASE):
                continue
            
            matches = pattern.findall(text)
            if matches:
                pii_found.append(pii_type)
        
        if pii_found:
            result.has_pii = True
            result.pii_types_found = pii_found
            result.is_safe = False
            # Redact PII from text
            result.redacted_text = self._redact_pii(text)
        
        return result
    
    def _check_medco_confidentiality(self, text: str) -> PrivacyCheckResult:
        """Check for Medco confidential keywords."""
        result = PrivacyCheckResult()
        text_lower = text.lower()
        found_keywords = []
        
        for kw in MEDCO_CONFIDENTIAL_KEYWORDS:
            if kw.lower() in text_lower:
                found_keywords.append(kw)
        
        # Also check sensitive context keywords
        for kw in SENSITIVE_CONTEXT_KEYWORDS:
            if kw.lower() in text_lower:
                found_keywords.append(kw)
        
        if found_keywords:
            result.has_confidential_project_data = True
            result.confidential_keywords_found = found_keywords
            result.is_safe = False
        
        return result
    
    def _redact_pii(self, text: str) -> str:
        """Redact PII from text."""
        redacted = text
        
        # Redact emails
        redacted = PII_PATTERNS["email"].sub("[EMAIL_REDACTED]", redacted)
        
        # Redact IPv4
        redacted = PII_PATTERNS["ipv4"].sub("[IP_REDACTED]", redacted)
        
        # Redact IPv6
        redacted = PII_PATTERNS["ipv6"].sub("[IPV6_REDACTED]", redacted)
        
        # Redact passwords
        redacted = PII_PATTERNS["password"].sub("[PASSWORD_REDACTED]", redacted)
        
        # Redact phone numbers
        redacted = PII_PATTERNS["phone_indonesia"].sub("[PHONE_REDACTED]", redacted)
        
        # Redact NIK
        redacted = PII_PATTERNS["nik_ktp"].sub("[NIK_REDACTED]", redacted)
        
        # Redact credit cards
        redacted = PII_PATTERNS["credit_card"].sub("[CC_REDACTED]", redacted)
        
        # Redact API keys
        redacted = PII_PATTERNS["api_key"].sub("[API_KEY_REDACTED]", redacted)
        
        return redacted
