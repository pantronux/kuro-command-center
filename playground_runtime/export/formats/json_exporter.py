"""JSON report exporter."""

import json


def export_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
