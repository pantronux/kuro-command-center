"""
Kuro AI V4.0 - Tone Guardrail
================================================================================
Validator for habit scolding/evaluation responses:
1. Logical Consequence Check: Must contain impact analysis of poor habits
2. Profanity Filter: No offensive language allowed
3. Professional Mentor Tone: Must maintain constructive, professional tone
"""
import logging
import re
from typing import List, Optional
from kuro_backend.guardrails.schemas import GuardrailResult, ValidationFailure, ScoldingResponse

logger = logging.getLogger(__name__)

# Indonesian profanity list (common ones to filter)
PROFANITY_PATTERNS = [
    re.compile(r'\b(anjing|anj|bangsat|bgst|bajingan|bngst|kontol|kntl|tolol|stupid|idiot|goblok|gblk|memek|mmk|tai|tahi|sialan|slan|brengsek|brgsk|bego|bg)\b', re.IGNORECASE),
    re.compile(r'\b(fuck|shit|damn|bitch|ass|dick|pussy|bastard|cunt)\b', re.IGNORECASE),
]

# Logical consequence indicators
# These phrases show that the response explains the IMPACT of poor habits
LOGICAL_CONSEQUENCE_INDICATORS = [
    # Indonesian
    "akibatnya", "dampaknya", "konsekuensi", "berpengaruh", "mempengaruhi",
    "menyebabkan", "mengakibatkan", "berisiko", "risiko", "bahaya",
    "jika tidak", "bila tidak", "tanpa itu", "dapat menyebabkan",
    "akan berdampak", "berakibat", "menghambat", "mengurangi", "menurunkan",
    "merusak", "mengganggu", "tidak akan", "sulit untuk",
    # English
    "consequence", "impact", "risk", "affect", "lead to", "result in",
    "cause", "hinder", "reduce", "decrease", "damage", "prevent",
    "will not", "cannot", "difficult to", "harder to",
]

# Motivation indicators
MOTIVATION_INDICATORS = [
    # Indonesian
    "semangat", "terus", "lanjutkan", "pertahankan", "kamu bisa", "anda bisa",
    "jangan menyerah", "pasti berhasil", "sukses", "berhasil", "maju",
    "tingkatkan", "lebih baik", "optimalkan", "rajin", "disiplin",
    "motivasi", "ayo", "mari", "yuk", "keep", "great job", "bagus",
    # English
    "keep it up", "well done", "good job", "great work", "excellent",
    "proud", "impressive", "motivation", "discipline", "consistency",
    "you can", "don't give up", "stay strong", "push through",
]

# Professional tone indicators
PROFESSIONAL_TONE_INDICATORS = [
    # Constructive language
    "saya sarankan", "saya merekomendasikan", "disarankan", "sebaiknya",
    "pertimbangkan", "evaluasi", "tinjau", "perbaiki", "tingkatkan",
    "analisis", "strategi", "rencana", "target", "goal",
    "professional", "mentor", "coaching", "guidance",
]


class ToneGuardrail:
    """
    Validates scolding/evaluation responses for tone and content.
    
    Rules:
    1. Must contain at least one logical consequence (impact analysis)
    2. Must NOT contain profanity
    3. Should end with motivation/encouragement
    4. Must maintain professional mentor tone
    """
    
    def __init__(self):
        self.name = "tone_guardrail"
    
    def validate(
        self,
        response_text: str,
        user_query: str = "",
        is_scolding: bool = False
    ) -> GuardrailResult:
        """
        Validate a scolding/evaluation response.
        
        Args:
            response_text: The generated response text
            user_query: Original user query
            is_scolding: Whether this is a scolding/evaluation response
            
        Returns:
            GuardrailResult with validation status
        """
        failures = []
        
        # Check 1: Profanity filter (always critical)
        profanity_result = self._check_profanity(response_text)
        if profanity_result:
            failures.append(profanity_result)
        
        # Check 2: Logical consequence (required for scolding)
        if is_scolding:
            consequence_failure = self._check_logical_consequence(response_text)
            if consequence_failure:
                failures.append(consequence_failure)
            
            # Check 3: Motivation (should be present)
            motivation_failure = self._check_motivation(response_text)
            if motivation_failure:
                failures.append(motivation_failure)
        
        # Check 4: Professional tone
        tone_failure = self._check_professional_tone(response_text)
        if tone_failure:
            failures.append(tone_failure)
        
        is_valid = len([f for f in failures if f.severity == "critical"]) == 0
        
        result = GuardrailResult(
            is_valid=is_valid,
            failures=failures
        )
        
        if not is_valid:
            logger.warning(
                f"[TONE_GUARDRAIL] Validation failed: {result.failure_summary} | "
                f"Query: {user_query[:80]}..."
            )
        else:
            logger.info(f"[TONE_GUARDRAIL] Validation passed for query: {user_query[:50]}...")
        
        return result
    
    def _check_profanity(self, text: str) -> Optional[ValidationFailure]:
        """Check for profanity in text."""
        for pattern in PROFANITY_PATTERNS:
            if pattern.search(text):
                return ValidationFailure(
                    guardrail_type="tone",
                    rule_violated="profanity_detected",
                    severity="critical",
                    detail="Respons mengandung kata-kata kasar yang tidak sesuai dengan persona Mentor Profesional.",
                    suggestion="Ganti kata kasar dengan bahasa yang profesional dan konstruktif. Kuro adalah mentor, bukan musuh."
                )
        return None
    
    def _check_logical_consequence(self, text: str) -> Optional[ValidationFailure]:
        """Check if response contains logical consequences."""
        text_lower = text.lower()
        has_consequence = any(ind in text_lower for ind in LOGICAL_CONSEQUENCE_INDICATORS)
        
        if not has_consequence:
            return ValidationFailure(
                guardrail_type="tone",
                rule_violated="no_logical_consequence",
                severity="critical",
                detail="Respons omelan tidak mengandung analisis dampak logis dari kebiasaan buruk.",
                suggestion="Jelaskan KONSEKUENSI NYATA dari kebiasaan buruk. Contoh: 'Jika jarang gym, progres hipertrofi akan stagnan dan otot kehilangan massa.'"
            )
        return None
    
    def _check_motivation(self, text: str) -> Optional[ValidationFailure]:
        """Check if response ends with motivation."""
        text_lower = text.lower()
        has_motivation = any(ind in text_lower for ind in MOTIVATION_INDICATORS)
        
        if not has_motivation:
            return ValidationFailure(
                guardrail_type="tone",
                rule_violated="no_motivation",
                severity="warning",
                detail="Respons tidak diakhiri dengan motivasi atau dorongan semangat.",
                suggestion="Akhiri evaluasi dengan kata-kata motivasi. Contoh: 'Tetap semangat, Master. Disiplin adalah kunci kesuksesan jangka panjang.'"
            )
        return None
    
    def _check_professional_tone(self, text: str) -> Optional[ValidationFailure]:
        """Check for professional mentor tone."""
        text_lower = text.lower()
        
        # Check for aggressive/demeaning language
        aggressive_patterns = [
            re.compile(r'\b(kamu (tidak|gak|nggak) becus|kamu bodoh|kamu malas|kamu payah)\b', re.IGNORECASE),
            re.compile(r'\b(kenapa (sih|kok|cuma|begitu))\b', re.IGNORECASE),
        ]
        
        for pattern in aggressive_patterns:
            if pattern.search(text):
                return ValidationFailure(
                    guardrail_type="tone",
                    rule_violated="unprofessional_tone",
                    severity="warning",
                    detail="Respons menggunakan bahasa yang merendahkan, bukan mentor profesional.",
                    suggestion="Gunakan bahasa yang konstruktif. Alih-alih 'kamu malas', gunakan 'konsistensi perlu ditingkatkan untuk hasil optimal'."
                )
        
        return None
    
    def analyze_scolding(self, text: str) -> ScoldingResponse:
        """
        Analyze a scolding response and return structured analysis.
        Useful for debugging and logging.
        """
        text_lower = text.lower()
        
        has_consequence = any(ind in text_lower for ind in LOGICAL_CONSEQUENCE_INDICATORS)
        has_motivation = any(ind in text_lower for ind in MOTIVATION_INDICATORS)
        has_profanity = any(p.search(text) for p in PROFANITY_PATTERNS)
        
        # Calculate tone score (simple heuristic)
        professional_count = sum(1 for ind in PROFESSIONAL_TONE_INDICATORS if ind in text_lower)
        aggressive_patterns = [
            re.compile(r'\b(kamu (tidak|gak|nggak) becus|kamu bodoh|kamu malas|kamu payah)\b', re.IGNORECASE),
            re.compile(r'\b(kenapa (sih|kok|cuma|begitu))\b', re.IGNORECASE),
        ]
        aggressive_count = sum(1 for p in aggressive_patterns if p.search(text))
        
        total_indicators = professional_count + aggressive_count
        if total_indicators > 0:
            tone_score = professional_count / total_indicators
        else:
            tone_score = 0.5  # Neutral if no indicators found
        
        return ScoldingResponse(
            evaluation_text=text,
            has_logical_consequence=has_consequence,
            has_motivation=has_motivation,
            contains_profanity=has_profanity,
            tone_score=round(tone_score, 2)
        )
