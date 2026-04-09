#!/usr/bin/env python3
"""Quick manual checks for Sniper guardrails (run from repo root with .env)."""
import logging

from dotenv import load_dotenv

load_dotenv()

# CLI smoke: one INFO line on success; use DEBUG for verbose guardrail logs
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
_log = logging.getLogger(__name__)

from kuro_backend.guardrails import sniper_context as sniper_ctx  # noqa: E402
from kuro_backend.guardrails import sniper_pipeline  # noqa: E402


def main():
    assert sniper_pipeline.sniper_precheck_or_block("sudo ls") is not None
    assert sniper_pipeline.sniper_precheck_or_block("tolong refactor function python ini") is None
    assert sniper_pipeline.sniper_validate_and_maybe_block_input("halo") is None
    assert sniper_pipeline.sniper_validate_and_maybe_block_input("I hate all XYZ kill them") is not None
    out = sniper_pipeline.sniper_postprocess_output("user", "Sebuah jawaban netral.")
    assert out
    cmd_user = "Tambahkan reminder besok jam 10 untuk audit ISO 27001 dengan klien Foo Bar"
    assert not sniper_ctx.should_fact_check_heuristic(cmd_user)
    comp_user = "Jelaskan klausul A.5.1 ISO 27001:2022 dan hubungannya dengan UU PDP"
    assert not sniper_ctx.should_fact_check_heuristic(comp_user)
    habit_user = "Riwayat gym saya dan streak belajar bulan ini berapa kali selesai"
    assert sniper_ctx.should_fact_check_heuristic(habit_user)
    refused = sniper_pipeline.sniper_postprocess_output(
        cmd_user, "Rencana konteks ISO 27001 untuk Foo Bar."
    )
    assert "tidak memiliki data faktual" not in (refused or "").lower()
    factish = "Compare Foo Corporation and Bar Incorporated projected impact for 2026"
    assert sniper_ctx.should_fact_check_heuristic(factish)
    tool_like = "Baik Pantronux, saya catat pengingat untuk **x** pada Monday. Benar, Master?"
    assert "tidak memiliki data faktual" not in (
        sniper_pipeline.sniper_postprocess_output(factish, tool_like) or ""
    ).lower()
    general_q = "Jelaskan prinsip chain of custody dalam forensik digital"
    labeled = sniper_pipeline.sniper_postprocess_output(general_q, "Jawaban umum forensik.")
    assert "tidak memiliki data faktual" not in (labeled or "").lower()
    assert (labeled or "").lstrip().startswith("[Kuro Analysis]")
    pre_labeled = "[Kuro Analysis]\nAnalisis awal sudah berlabel."
    no_dup = sniper_pipeline.sniper_postprocess_output(general_q, pre_labeled)
    assert (no_dup or "").count("[Kuro Analysis]") == 1
    _log.info("smoke_sniper_guardrails: OK")


if __name__ == "__main__":
    main()
