"""Forensic bundle exporter for portable trust packages."""

from pathlib import Path
import json
import zipfile
from hashlib import sha256


class ForensicBundleExporter:
    def export_bundle(self, session_id: str, bundle_payload: dict, output_path: str | None = None) -> dict:
        if output_path:
            zip_path = Path(output_path)
        else:
            stamp = bundle_payload.get("created_at") or "snapshot"
            safe_stamp = str(stamp).replace(":", "-").replace(" ", "_")
            zip_path = Path("exports") / f"playground-forensic-bundle-{session_id}-{safe_stamp}.zip"

        zip_path.parent.mkdir(parents=True, exist_ok=True)

        raw_rows = bundle_payload.get("raw", [])
        canonical_rows = bundle_payload.get("canonical", [])
        manifests = bundle_payload.get("manifests", [])
        hashes = bundle_payload.get("hashes", {})
        custody = bundle_payload.get("custody", [])
        ontology = bundle_payload.get("ontology", {})
        reports = bundle_payload.get("reports", [])

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for idx, row in enumerate(raw_rows):
                name = row.get("id") or f"raw-{idx+1}"
                archive.writestr(f"raw/{name}.json", json.dumps(row, ensure_ascii=False, indent=2))
            for idx, row in enumerate(canonical_rows):
                name = row.get("id") or f"canonical-{idx+1}"
                archive.writestr(f"canonical/{name}.json", json.dumps(row, ensure_ascii=False, indent=2))
            for idx, row in enumerate(manifests):
                name = row.get("manifest_id") or row.get("id") or f"manifest-{idx+1}"
                archive.writestr(f"manifests/{name}.json", json.dumps(row, ensure_ascii=False, indent=2))

            archive.writestr("hashes/integrity_ledger.json", json.dumps(hashes, ensure_ascii=False, indent=2))
            archive.writestr("custody/chain_of_custody.json", json.dumps(custody, ensure_ascii=False, indent=2))
            archive.writestr("ontology/ontology.json", json.dumps(ontology, ensure_ascii=False, indent=2))
            graphs = ontology.get("graphs", []) if isinstance(ontology, dict) else []
            jsonld_rows = [row.get("graph_jsonld") for row in graphs if isinstance(row, dict) and row.get("graph_jsonld")]
            rdf_star_rows = [row.get("graph_rdf_star") for row in graphs if isinstance(row, dict) and row.get("graph_rdf_star")]
            archive.writestr("ontology/jsonld.json", json.dumps(jsonld_rows, ensure_ascii=False, indent=2))
            archive.writestr("ontology/rdf_star.json", json.dumps(rdf_star_rows, ensure_ascii=False, indent=2))
            archive.writestr("reports/reports.json", json.dumps(reports, ensure_ascii=False, indent=2))
            archive.writestr("reports/summary.md", self._build_summary_markdown(bundle_payload))

        zip_hash = sha256(zip_path.read_bytes()).hexdigest()
        return {
            "bundle_path": str(zip_path),
            "bundle_sha256": zip_hash,
            "bundle_size_bytes": zip_path.stat().st_size,
        }

    def _build_summary_markdown(self, bundle_payload: dict) -> str:
        trust = bundle_payload.get("trust_summary", {})
        lines = [
            "# Forensic Trust Summary",
            "",
            f"Session Integrity: {trust.get('session_integrity', 'UNVERIFIED')}",
            f"Snapshot Status: {trust.get('snapshot_status', 'UNVERIFIED')}",
            f"Replay Compatibility: {trust.get('replay_compatibility', 'LIMITED')}",
            "",
            "## Notes",
        ]
        for note in trust.get("notes", []):
            lines.append(f"- {note}")
        if not trust.get("notes"):
            lines.append("- No additional notes.")
        return "\n".join(lines) + "\n"
