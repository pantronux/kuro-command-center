"""CSV report exporter."""

import csv
import io


def export_csv(report: dict) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["section", "key", "value"])
    for key, value in report.items():
        writer.writerow(["root", key, str(value)])
    return out.getvalue()
