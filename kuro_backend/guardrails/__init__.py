"""Sniper NeMo Guardrails integration (input/output rails around LangGraph).

--- Header Doc ---
Purpose: Package marker for Sniper guardrails; triggers nemo_bootstrap on import.
Caller: langgraph_core at startup, tests.
Dependencies: submodules (sniper_pipeline, nemo_bootstrap, jailbreak_precheck).
Main Functions: Re-exports sniper rail entrypoints.
Side Effects: None at bare import (submodules loaded lazily).
"""
