"""Research export placeholders.

The app split introduces the boundary first. Concrete paper/report exporters can
reuse the existing universal export engine after the route contracts stabilize.
"""
from __future__ import annotations

from typing import Any, Dict


def build_research_export_manifest(project: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "project_id": project.get("project_id", ""),
        "title": project.get("title", ""),
        "export_scope": "research_project",
    }
