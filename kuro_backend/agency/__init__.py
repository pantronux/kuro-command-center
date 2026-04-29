"""
Kuro AI — Natural Agency Sub-package (Tomasello 2025)
=======================================================
Implements the Three-Tier Control System:
  T1 - Executive / Intentional Agent  (executive_monitor_node)
  T2 - Rational / Metacognitive Agent (metacognitive_review_node)
  T3 - Social / Shared Agency         (joint_goal_store)

--- Header Doc ---
Purpose: Package root for the Natural Agency tier. Re-exports key helpers for convenience.
Caller: langgraph_core.py (nodes), memory_coordinator.py (evaluate_alignment).
Dependencies: joint_goal_store, cognitive_effort.
Main Functions: (see sub-modules)
Side Effects: None at import.
"""
