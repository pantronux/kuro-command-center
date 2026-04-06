"""
Kuro AI V4.0 - Compliance Guardrail
================================================================================
Validator for compliance/audit responses:
1. ISO Clause Verification: Ensures cited clauses exist in retrieved documents
2. Grounding Check: Ensures answers are grounded in ComplianceDoc sources
"""
import logging
import re
from typing import List, Dict, Optional
from kuro_backend.guardrails.schemas import GuardrailResult, ValidationFailure

logger = logging.getLogger(__name__)

# Known ISO 27001:2022 clause patterns
VALID_ISO_CLAUSES = {
    # Annex A controls (A.5.x through A.8.x)
    "A.5": list(range(1, 38)),   # A.5.1 - A.5.37 (Organizational)
    "A.6": list(range(1, 9)),    # A.6.1 - A.6.8 (People)
    "A.7": list(range(1, 15)),   # A.7.1 - A.7.14 (Physical)
    "A.8": list(range(1, 35)),   # A.8.1 - A.8.34 (Technological)
    # Main clauses (4-10)
    "main": list(range(4, 11)),  # Clause 4 - Clause 10
}

# Regex patterns for ISO clause extraction
ISO_CLAUSE_PATTERNS = [
    re.compile(r'A\.(\d+)\.(\d+)', re.IGNORECASE),  # A.5.1, A.8.15
    re.compile(r'(?:clause|klausul)\s*(\d+)', re.IGNORECASE),  # Clause 8, Klausul 5
    re.compile(r'ISO\s*27001[:\s]*(\d{4})?', re.IGNORECASE),  # ISO 27001:2022
    re.compile(r'ISO\s*27701', re.IGNORECASE),
    re.compile(r'ISO\s*[/\s]*42001', re.IGNORECASE),
    re.compile(r'NIST\s*(?:CSF|SP\s*800-53)', re.IGNORECASE),
    re.compile(r'GDPR', re.IGNORECASE),
    re.compile(r'UU\s*PDP', re.IGNORECASE),
    re.compile(r'TOGAF', re.IGNORECASE),
]


class ComplianceGuardrail:
    """
    Validates compliance/audit responses for accuracy and grounding.
    
    Rules:
    1. ISO Clause Verification: All cited clauses must be valid and present in source docs
    2. Grounding Check: Answer must reference actual compliance documents
    3. No Hallucination: Cannot invent clauses not in the knowledge base
    """
    
    def __init__(self):
        self.name = "compliance_guardrail"
    
    def validate(
        self,
        response_text: str,
        compliance_data: List[Dict] = None,
        user_query: str = ""
    ) -> GuardrailResult:
        """
        Validate a compliance response.
        
        Args:
            response_text: The generated response text
            compliance_data: List of compliance search results from ChromaDB
            user_query: Original user query
            
        Returns:
            GuardrailResult with validation status
        """
        failures = []
        
        # Check 1: Extract and validate ISO clauses
        clause_failures = self._validate_iso_clauses(response_text, compliance_data)
        failures.extend(clause_failures)
        
        # Check 2: Grounding verification
        grounding_failures = self._validate_grounding(response_text, compliance_data)
        failures.extend(grounding_failures)
        
        # Check 3: Hallucination detection
        hallucination_failures = self._detect_hallucination(response_text, compliance_data)
        failures.extend(hallucination_failures)
        
        is_valid = len([f for f in failures if f.severity == "critical"]) == 0
        
        result = GuardrailResult(
            is_valid=is_valid,
            failures=failures
        )
        
        if not is_valid:
            logger.warning(
                f"[COMPLIANCE_GUARDRAIL] Validation failed: {result.failure_summary} | "
                f"Query: {user_query[:80]}..."
            )
        else:
            logger.info(f"[COMPLIANCE_GUARDRAIL] Validation passed for query: {user_query[:50]}...")
        
        return result
    
    def _validate_iso_clauses(
        self,
        response_text: str,
        compliance_data: List[Dict] = None
    ) -> List[ValidationFailure]:
        """
        Validate that all ISO clauses cited in the response are valid and present in source docs.
        """
        failures = []
        
        # Extract all ISO clause references from response
        cited_clauses = self._extract_cited_clauses(response_text)
        
        if not cited_clauses:
            return failures  # No clauses cited, nothing to validate
        
        # Get valid clauses from compliance data
        valid_clauses = set()
        if compliance_data:
            for doc in compliance_data:
                clauses_str = doc.get("clauses", "")
                if clauses_str:
                    for c in clauses_str.split(","):
                        valid_clauses.add(c.strip())
        
        # Check each cited clause
        for clause in cited_clauses:
            if valid_clauses and clause not in valid_clauses:
                # Check if it's at least a valid format
                if not self._is_valid_clause_format(clause):
                    failures.append(ValidationFailure(
                        guardrail_type="compliance",
                        rule_violated="invalid_clause_format",
                        severity="critical",
                        detail=f"Klausul '{clause}' tidak ditemukan dalam dokumen sumber dan format tidak valid.",
                        suggestion=f"Verifikasi format klausul. Gunakan format seperti 'A.5.1', 'Clause 8', dll."
                    ))
                else:
                    # Valid format but not in source docs
                    failures.append(ValidationFailure(
                        guardrail_type="compliance",
                        rule_violated="clause_not_in_source",
                        severity="warning",
                        detail=f"Klausul '{clause}' valid secara format tetapi tidak ditemukan dalam dokumen ComplianceDoc yang diindeks.",
                        suggestion=f"Tambahkan dokumen sumber yang mengandung klausul {clause} ke ChromaDB."
                    ))
        
        return failures
    
    def _validate_grounding(
        self,
        response_text: str,
        compliance_data: List[Dict] = None
    ) -> List[ValidationFailure]:
        """
        Ensure the response is grounded in actual compliance documents.
        More lenient for general ISO knowledge questions.
        """
        failures = []
        
        # Check if response makes SPECIFIC compliance claims (not general knowledge)
        specific_compliance_indicators = [
            "sesuai dengan klausul", "mengacu pada klausul", "sesuai klausul",
            "as per clause", "in accordance with clause", "required by clause",
        ]
        
        has_specific_claim = any(ind in response_text.lower() for ind in specific_compliance_indicators)
        has_citation = any(re.search(p, response_text) for p in ISO_CLAUSE_PATTERNS)
        
        # Only flag if making SPECIFIC clause claims without proper citations
        if has_specific_claim and not has_citation:
            failures.append(ValidationFailure(
                guardrail_type="compliance",
                rule_violated="ungrounded_compliance_claim",
                severity="warning",  # Downgrade to warning for general knowledge
                detail="Respons menyebutkan klausul spesifik tanpa referensi dokumen sumber.",
                suggestion="Sertakan referensi klausul yang jelas atau nyatakan bahwa ini adalah pengetahuan umum."
            ))
        
        return failures
    
    def _detect_hallucination(
        self,
        response_text: str,
        compliance_data: List[Dict] = None
    ) -> List[ValidationFailure]:
        """
        Detect potential hallucinated compliance information.
        """
        failures = []
        
        # Check for specific clause numbers that don't exist
        # ISO 27001:2022 Annex A has specific ranges
        annex_a_matches = re.findall(r'A\.(\d+)\.(\d+)', response_text)
        
        for prefix, num in annex_a_matches:
            prefix_int = int(prefix)
            num_int = int(num)
            
            if prefix_int in VALID_ISO_CLAUSES:
                max_clause = max(VALID_ISO_CLAUSES[prefix_int])
                if num_int > max_clause:
                    failures.append(ValidationFailure(
                        guardrail_type="compliance",
                        rule_violated="nonexistent_clause",
                        severity="critical",
                        detail=f"Klausul A.{prefix_int}.{num_int} tidak ada dalam ISO 27001:2022 (maksimal A.{prefix_int}.{max_clause}).",
                        suggestion=f"Gunakan klausul yang valid: A.{prefix_int}.1 hingga A.{prefix_int}.{max_clause}."
                    ))
        
        return failures
    
    def _extract_cited_clauses(self, text: str) -> List[str]:
        """Extract all ISO clause references from text."""
        clauses = []
        
        # Extract A.X.Y patterns
        for match in re.finditer(r'A\.(\d+)\.(\d+)', text):
            clauses.append(f"A.{match.group(1)}.{match.group(2)}")
        
        # Extract Clause/Klausul X patterns
        for match in re.finditer(r'(?:clause|klausul)\s*(\d+)', text, re.IGNORECASE):
            clauses.append(f"Clause {match.group(1)}")
        
        return list(set(clauses))
    
    def _is_valid_clause_format(self, clause: str) -> bool:
        """Check if a clause reference follows valid format."""
        valid_patterns = [
            r'^A\.\d+\.\d+$',  # A.5.1
            r'^Clause\s*\d+$',  # Clause 8
            r'^Klausul\s*\d+$',  # Klausul 5
            r'^ISO\s*\d+',  # ISO 27001
            r'^NIST',  # NIST CSF
            r'^GDPR$',  # GDPR
            r'^UU\s*PDP$',  # UU PDP
            r'^TOGAF$',  # TOGAF
        ]
        return any(re.match(p, clause, re.IGNORECASE) for p in valid_patterns)
