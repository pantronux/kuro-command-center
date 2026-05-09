"""
Playground API package.

--- Header Doc ---
Purpose: Router factory + schema contracts for KPR API.
Caller: main.py conditional mount.
Dependencies: api.router.
Main Functions: create_playground_router().
Side Effects: None.
"""

from .router import create_playground_router

__all__ = ["create_playground_router"]
