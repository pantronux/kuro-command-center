"""RDF-like report exporter."""


def export_rdf(report: dict) -> str:
    lines = []
    sid = report.get("session_metadata", {}).get("session_id", "unknown")
    lines.append(f"session:{sid} a :ForensicReport .")
    for key, value in report.get("evaluation", {}).items():
        lines.append(f"session:{sid} :{key} \"{value}\" .")
    return "\n".join(lines)
