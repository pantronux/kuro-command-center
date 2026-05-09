from __future__ import annotations


def render_uncertainty(confidence_score: float) -> str:
    if confidence_score < 0.35:
        return "Saya belum punya cukup bukti yang ter-grounding untuk menjawab ini secara presisi."
    if confidence_score < 0.55:
        return "Bukti yang tersedia masih lemah, jadi jawaban ini perlu verifikasi tambahan."
    if confidence_score < 0.75:
        return "Ini adalah inferensi berbasis bukti parsial; saya sarankan verifikasi jika dipakai untuk keputusan penting."
    return ""
