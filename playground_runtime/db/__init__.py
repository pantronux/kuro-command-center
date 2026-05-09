"""
DB package.

--- Header Doc ---
Purpose: Manage isolated KPR SQLite schema and persistence APIs.
Caller: runtime service and tests.
Dependencies: playground_db.
Main Functions: PlaygroundDB.
Side Effects: Creates/updates kuro_playground.db.
"""

from .playground_db import PlaygroundDB

__all__ = ["PlaygroundDB"]
