"""
Kuro Playground Runtime package.

--- Header Doc ---
Purpose: Isolated forensic runtime package entrypoint.
Caller: main.py conditional mount and playground tests.
Dependencies: playground_runtime submodules only.
Main Functions: get_settings().
Side Effects: None.
"""

from .config import get_settings

__all__ = ["get_settings"]
