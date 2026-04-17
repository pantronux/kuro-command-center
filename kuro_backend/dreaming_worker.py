"""Kuro AI V6.0 "Sovereign" — Autonomous Memory Dreaming worker.

A reflection worker that runs while the system is idle. Pipeline:

1. Acquire SQLite advisory lease (15 min TTL) to prevent overlap across
   APScheduler + CLI invocations.
2. Idle gate: abort when Master interacted recently (< KURO_DREAMING_IDLE_MIN).
3. Collect last 24h of ``short_term_summaries`` + ``research_ledger``.
4. Ask Gemini (``response_schema`` constrained) to identify:
     - inconsistencies across personas / sessions
     - unresolved Master questions
     - references that deserve deeper research
5. For each finding with ``confidence < threshold`` and a non-empty
   ``search_query``, enrich via OpenClaw ``google_search`` skill (primary)
   with ``serper_search`` fallback. Summaries land in Chroma Layer 2 with a
   ``tag=dream-insight`` metadata marker.
6. Bump SSoT revision ONLY when ``ssot_bump_recommended`` is set and the
   finding clears the confidence floor.
7. Proactively notify Master via Telegram for ``inconsistency`` findings,
   dedup'd by sha1 fingerprint so we never re-spam the same issue.

Safety:
- All SQLite writes use fresh short-lived connections + short transactions.
- All outbound network calls have explicit timeouts; failures degrade the
  cycle, they never crash the parent process.
- Kill switches via environment variables make it easy to disable segments
  in production without redeploys.

Run as a module: ``python3 -m kuro_backend.dreaming_worker``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import socket
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Final, List, Optional, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment / constants
# ---------------------------------------------------------------------------

_LEASE_NAME: Final[str] = "dreaming"
_LEASE_TTL_S: Final[int] = 900  # 15 min

_ENV_ENABLED: Final[str] = "KURO_DREAMING_ENABLED"
_ENV_SEARCH: Final[str] = "KURO_DREAMING_SEARCH_ENABLED"
_ENV_CONF: Final[str] = "KURO_DREAMING_CONFIDENCE_THRESHOLD"
_ENV_IDLE_MIN: Final[str] = "KURO_DREAMING_IDLE_MIN"
_ENV_LOOKBACK: Final[str] = "KURO_DREAMING_LOOKBACK_HOURS"
_ENV_MAX_FINDINGS: Final[str] = "KURO_DREAMING_MAX_FINDINGS"

# CVE sentinel gates (V5.5 Jarvis wave).
_ENV_CVE_ENABLED: Final[str] = "KURO_CVE_SENTINEL_ENABLED"
_ENV_CVE_MIN_CVSS: Final[str] = "KURO_CVE_MIN_CVSS"
_ENV_CVE_MAX_ALERTS: Final[str] = "KURO_CVE_MAX_ALERTS_PER_CYCLE"
_CVE_SCAN_TIMEOUT_S: Final[float] = 30.0
_NVD_ENDPOINT: Final[str] = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_NVD_STAGGER_S: Final[float] = 6.1


def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, "true" if default else "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Reflection schema
# ---------------------------------------------------------------------------

_REFLECTION_SCHEMA: Final[Dict[str, Any]] = {
    "type": "object",
    "properties": {
        "overall_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["inconsistency", "unresolved_question", "deep_research"],
                    },
                    "persona_scope": {"type": "string"},
                    "description": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "search_query": {"type": "string"},
                    "ssot_bump_recommended": {"type": "boolean"},
                    "suggested_fix": {"type": "string"},
                },
                "required": ["kind", "persona_scope", "description", "confidence"],
            },
        },
    },
    "required": ["findings", "overall_risk"],
}


_REFLECTION_SYSTEM_INSTRUCTION: Final[str] = (
    "Anda adalah Kuro dalam mode 'dreaming / reflection'. Tugas Anda: baca "
    "ringkasan percakapan dan ledger riset 24 jam terakhir, lalu deteksi: "
    "(1) inkonsistensi antar-persona / antar-sesi, "
    "(2) pertanyaan Master yang belum terjawab tuntas, "
    "(3) referensi yang perlu diperdalam (paper/regulasi/teknik). "
    "Untuk tiap temuan berikan confidence (0..1) — rendah jika Anda perlu "
    "sumber eksternal untuk verifikasi. Isi search_query hanya jika "
    "confidence < 0.7 dan pencarian Google akan membantu. Set "
    "ssot_bump_recommended=true HANYA jika ada fakta baru yang krusial "
    "untuk SSoT (habits/reminders/profil)."
)


@dataclass
class Finding:
    kind: str
    persona_scope: str
    description: str
    confidence: float
    id: str = ""
    evidence: List[str] = field(default_factory=list)
    search_query: str = ""
    ssot_bump_recommended: bool = False
    suggested_fix: str = ""


def _coerce_findings(raw: Any) -> tuple[List[Finding], str]:
    """Normalize Gemini reflection output into ``list[Finding]``.

    Returns (findings, overall_risk). Gracefully handles None, string JSON,
    or already-parsed dicts.
    """
    parsed: Dict[str, Any] = {}
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            parsed = {}
    overall_risk = str(parsed.get("overall_risk") or "low").lower()
    items = parsed.get("findings") or []
    if not isinstance(items, list):
        return [], overall_risk
    findings: List[Finding] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        try:
            conf_raw = item.get("confidence", 0.0)
            confidence = float(conf_raw) if conf_raw is not None else 0.0
        except (TypeError, ValueError):
            confidence = 0.0
        kind = str(item.get("kind") or "").strip()
        if kind not in ("inconsistency", "unresolved_question", "deep_research"):
            continue
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        evidence_list = item.get("evidence") or []
        evidence = [str(e).strip() for e in evidence_list if str(e).strip()]
        findings.append(Finding(
            kind=kind,
            persona_scope=str(item.get("persona_scope") or "").strip() or "consultant",
            description=description,
            confidence=max(0.0, min(1.0, confidence)),
            id=str(item.get("id") or f"f{idx}"),
            evidence=evidence,
            search_query=str(item.get("search_query") or "").strip(),
            ssot_bump_recommended=bool(item.get("ssot_bump_recommended")),
            suggested_fix=str(item.get("suggested_fix") or "").strip(),
        ))
    return findings, overall_risk


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

def collect_last_24h(lookback_hours: int = 24) -> Dict[str, Any]:
    """Read last-N-hours reflection input from SQLite.

    Returns a small dict with ``summaries``, ``ledger``, and ``personas_active``
    keys. Uses fresh short-lived connections so writers are never blocked.
    """
    from kuro_backend import memory_manager

    cutoff = (datetime.now() - timedelta(hours=max(1, int(lookback_hours)))).isoformat(
        timespec="seconds"
    )

    raw_summaries = memory_manager.query_short_term_summaries_recent(limit=50)
    summaries: List[Dict[str, Any]] = []
    personas_active: set[str] = set()
    for row in raw_summaries:
        if row.get("updated_at", "") < cutoff:
            continue
        try:
            summary_json = json.loads(row.get("summary_json") or "{}")
        except json.JSONDecodeError:
            summary_json = {}
        persona = str(row.get("persona_scope") or "consultant")
        personas_active.add(persona)
        summaries.append({
            "persona_scope": persona,
            "last_entry_id": row.get("last_entry_id", 0),
            "updated_at": row.get("updated_at", ""),
            "topic": str(summary_json.get("topic") or ""),
            "decisions": list(summary_json.get("decisions") or []),
            "novelty_points": list(summary_json.get("novelty_points") or []),
            "technical_specs": list(summary_json.get("technical_specs") or []),
            "compliance_refs": list(summary_json.get("compliance_refs") or []),
            "open_questions": list(summary_json.get("open_questions") or []),
            "entities": list(summary_json.get("entities") or []),
        })

    raw_ledger = memory_manager.query_research_ledger_since(cutoff, limit=500)
    ledger: List[Dict[str, Any]] = []
    for row in raw_ledger:
        personas_active.add(row.get("persona_scope", "consultant"))
        ledger.append({
            "id": row.get("id"),
            "persona_scope": row.get("persona_scope"),
            "kind": row.get("kind"),
            "content": row.get("content"),
            "created_at": row.get("created_at"),
        })

    return {
        "cutoff": cutoff,
        "summaries": summaries,
        "ledger": ledger,
        "personas_active": sorted(personas_active),
    }


# ---------------------------------------------------------------------------
# Reflection (Gemini with response_schema)
# ---------------------------------------------------------------------------

def _run_reflection(corpus: Dict[str, Any]) -> tuple[List[Finding], str]:
    """Call Gemini in reflection mode. Returns (findings, overall_risk)."""
    if not corpus.get("summaries") and not corpus.get("ledger"):
        return [], "low"
    try:
        from google.genai import types as genai_types
        from kuro_backend.config import PRIMARY_MODEL
        from kuro_backend.memory_coordinator import _get_summary_genai_client

        client = _get_summary_genai_client()
        corpus_blob = json.dumps(corpus, ensure_ascii=False)[:16000]
        response = client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=corpus_blob,
            config=genai_types.GenerateContentConfig(
                system_instruction=_REFLECTION_SYSTEM_INSTRUCTION,
                temperature=0.1,
                top_p=0.5,
                top_k=20,
                max_output_tokens=1024,
                response_mime_type="application/json",
                response_schema=_REFLECTION_SCHEMA,
            ),
        )
        parsed = getattr(response, "parsed", None)
        text = getattr(response, "text", "") or ""
        return _coerce_findings(parsed if parsed is not None else text)
    except Exception as exc:
        logger.warning("[DREAMING] reflection call failed: %s", exc)
        return [], "low"


# ---------------------------------------------------------------------------
# Enrichment (OpenClaw -> Serper fallback -> Chroma write)
# ---------------------------------------------------------------------------

_SEARCH_TIMEOUT_S: Final[float] = 8.0


def _google_via_openclaw(query: str) -> List[Dict[str, Any]]:
    """Primary search path — OpenClaw ``google_search`` skill.

    Returns a list of ``{title, snippet, link}`` dicts or ``[]`` on failure.
    """
    if not query:
        return []
    try:
        from kuro_backend.execution.service import execute_openclaw_skill_sync
    except Exception as exc:
        logger.warning("[DREAMING] openclaw import failed: %s", exc)
        return []
    try:
        result = execute_openclaw_skill_sync(
            "google_search", payload={"query": query, "num": 5}
        )
    except Exception as exc:
        logger.warning("[DREAMING] openclaw google_search raised: %s", exc)
        return []
    if not isinstance(result, dict):
        return []
    status = str(result.get("status") or "").lower()
    if status and status not in ("ok", "success", "completed"):
        logger.info("[DREAMING] openclaw non-ok status=%s", status)
        return []
    results = result.get("results") or result.get("organic_results") or []
    if not isinstance(results, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in results[:5]:
        if not isinstance(item, dict):
            continue
        normalized.append({
            "title": str(item.get("title") or "")[:300],
            "snippet": str(item.get("snippet") or item.get("description") or "")[:500],
            "link": str(item.get("link") or item.get("url") or "")[:500],
        })
    return normalized


def _google_via_serper(query: str) -> List[Dict[str, Any]]:
    """Fallback search — in-process Serper helper."""
    if not query:
        return []
    try:
        from kuro_backend.serper_tool import serper_search
    except Exception as exc:
        logger.warning("[DREAMING] serper import failed: %s", exc)
        return []
    try:
        result = serper_search(query, search_type="search", num_results=5)
    except Exception as exc:
        logger.warning("[DREAMING] serper_search raised: %s", exc)
        return []
    if not isinstance(result, dict) or result.get("error"):
        return []
    organic = result.get("organic_results") or []
    if not isinstance(organic, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in organic[:5]:
        if not isinstance(item, dict):
            continue
        normalized.append({
            "title": str(item.get("title") or "")[:300],
            "snippet": str(item.get("snippet") or "")[:500],
            "link": str(item.get("link") or "")[:500],
        })
    return normalized


def _search_with_fallback(query: str) -> tuple[List[Dict[str, Any]], str]:
    """Try OpenClaw first, fall back to Serper. Returns (results, source)."""
    openclaw_results = _google_via_openclaw(query)
    if openclaw_results:
        return openclaw_results, "openclaw"
    serper_results = _google_via_serper(query)
    if serper_results:
        return serper_results, "serper"
    return [], "none"


# ---------------------------------------------------------------------------
# Cyber Security Sentinel (Jarvis wave V5.5)
# ---------------------------------------------------------------------------

def _cve_severity(cvss: float) -> str:
    if cvss >= 9.0:
        return "critical"
    if cvss >= 7.0:
        return "high"
    if cvss >= 4.0:
        return "medium"
    return "low"


def _cve_scan_via_openclaw(
    *, min_cvss: float, max_cves_per_target: int,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Call the daemon ``vulnerability_scan`` skill.

    Returns ``(targets, cves)``. Empty lists signal the caller to try the
    direct NVD fallback.
    """
    try:
        from kuro_backend.execution.service import execute_openclaw_skill_sync
    except Exception as exc:
        logger.warning("[CVE] openclaw import failed: %s", exc)
        return [], []
    payload = {
        "min_cvss": float(min_cvss),
        "max_cves_per_target": int(max_cves_per_target),
    }
    try:
        result = execute_openclaw_skill_sync(
            "vulnerability_scan", payload=payload,
        )
    except Exception as exc:
        logger.warning("[CVE] openclaw vulnerability_scan raised: %s", exc)
        return [], []
    if not isinstance(result, dict) or not result.get("ok"):
        logger.info(
            "[CVE] openclaw non-ok result: %s",
            (result or {}).get("error_code") if isinstance(result, dict) else "invalid",
        )
        return [], []
    targets = result.get("targets") or []
    cves = result.get("cves") or []
    if not isinstance(targets, list):
        targets = []
    if not isinstance(cves, list):
        cves = []
    return targets, cves


def _discover_proxmox_targets_locally() -> List[Dict[str, Any]]:
    """Best-effort Proxmox target discovery for the direct NVD fallback.

    Reuses :func:`kuro_backend.tools.base_tools.check_proxmox_infrastructure`
    when available. Returns ``[{kind, id, software:[{name, version}]}]``.
    """
    try:
        from kuro_backend.tools.base_tools import check_proxmox_infrastructure
    except Exception as exc:
        logger.debug("[CVE] proxmox helper import failed: %s", exc)
        return []
    try:
        report = check_proxmox_infrastructure()
    except Exception as exc:
        logger.debug("[CVE] check_proxmox_infrastructure raised: %s", exc)
        return []
    if not report:
        return []
    if isinstance(report, dict):
        vms = report.get("vms") or report.get("targets") or []
        software = report.get("software") or []
    else:
        vms = []
        software = []
    host_target = {
        "kind": "host",
        "id": "proxmox",
        "software": software if isinstance(software, list) else [],
    }
    targets: List[Dict[str, Any]] = [host_target]
    if isinstance(vms, list):
        for vm in vms[:12]:
            if not isinstance(vm, dict):
                continue
            targets.append({
                "kind": "vm",
                "id": str(vm.get("id") or vm.get("vmid") or vm.get("name") or ""),
                "software": vm.get("software") or [],
            })
    return targets


def _cve_scan_via_nvd_direct(
    targets: List[Dict[str, Any]],
    *,
    min_cvss: float,
    max_cves_per_target: int,
) -> List[Dict[str, Any]]:
    """Query NVD directly when the OpenClaw daemon is unavailable.

    Honours the public anonymous rate limit (5 req / 30 s) with a ~6 s stagger.
    """
    try:
        import requests
    except ImportError:
        logger.warning("[CVE] requests not installed; NVD fallback unavailable")
        return []
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for target in targets or []:
        kept = 0
        for sw in (target.get("software") or []):
            if kept >= max_cves_per_target:
                break
            name = str((sw or {}).get("name") or "").strip().lower()
            version = str((sw or {}).get("version") or "").strip()
            if not name:
                continue
            keyword = f"{name} {version}".strip()
            if keyword in seen:
                continue
            seen.add(keyword)
            try:
                resp = requests.get(
                    _NVD_ENDPOINT,
                    params={"keywordSearch": keyword, "resultsPerPage": 25},
                    headers={"User-Agent": "Kuro-CVE-Sentinel/1.0"},
                    timeout=15,
                )
            except Exception as exc:
                logger.debug("[CVE] NVD request failed for %s: %s", keyword, exc)
                continue
            if resp.status_code != 200:
                logger.debug(
                    "[CVE] NVD returned %d for %s", resp.status_code, keyword,
                )
                time.sleep(_NVD_STAGGER_S)
                continue
            payload = resp.json() if resp.text else {}
            for item in (payload.get("vulnerabilities") or []):
                if kept >= max_cves_per_target:
                    break
                cve = (item or {}).get("cve") or {}
                cve_id = cve.get("id") or ""
                if not cve_id:
                    continue
                cvss = 0.0
                metrics = cve.get("metrics") or {}
                for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                    entries = metrics.get(key) or []
                    if entries:
                        data = (entries[0] or {}).get("cvssData") or {}
                        try:
                            cvss = float(data.get("baseScore") or 0.0)
                        except (TypeError, ValueError):
                            cvss = 0.0
                        break
                if cvss < min_cvss:
                    continue
                desc = ""
                for d in (cve.get("descriptions") or []):
                    if (d or {}).get("lang") == "en":
                        desc = str(d.get("value") or "")[:500]
                        break
                out.append({
                    "id": cve_id,
                    "cvss": round(cvss, 1),
                    "severity": _cve_severity(cvss),
                    "target_id": target.get("id"),
                    "software": name,
                    "version": version,
                    "title": cve_id,
                    "description": desc,
                    "published": cve.get("published") or "",
                    "references": [],
                })
                kept += 1
            time.sleep(_NVD_STAGGER_S)
    out.sort(key=lambda c: c.get("cvss") or 0.0, reverse=True)
    return out


def _persist_cve_alert(cve: Dict[str, Any], *, cycle_id: int) -> bool:
    """Write a CVE finding to Chroma Layer 2 with a ``cve-alert`` tag."""
    try:
        from kuro_backend import memory_manager

        cve_id = str(cve.get("id") or "CVE-UNKNOWN")
        cvss = cve.get("cvss")
        severity = str(cve.get("severity") or "unknown")
        software = str(cve.get("software") or "")
        version = str(cve.get("version") or "")
        target_id = str(cve.get("target_id") or "")
        content = (
            f"[CVE-ALERT] {cve_id} ({severity}, CVSS {cvss})\n"
            f"Target: {target_id} | Software: {software} {version}\n"
            f"{(cve.get('description') or '').strip()}"
        )
        memory_manager.add_long_term_v2(
            content,
            metadata={
                "source": "cve_sentinel",
                "tag": "cve-alert",
                "cve_id": cve_id,
                "cvss": cvss,
                "severity": severity,
                "target_id": target_id,
                "software": software,
                "version": version,
                "cycle_id": cycle_id,
            },
        )
        return True
    except Exception as exc:
        logger.warning("[CVE] chroma write failed cve=%s: %s", cve.get("id"), exc)
        return False


def _publish_cve_event(cve: Dict[str, Any]) -> bool:
    """Emit a ProactiveEvent so the bus handles dedup + Telegram."""
    try:
        from kuro_backend import proactive_events

        cve_id = str(cve.get("id") or "CVE-UNKNOWN")
        target_id = str(cve.get("target_id") or "unknown")
        severity = str(cve.get("severity") or "high").lower()
        bus_severity = "critical" if severity == "critical" else "warning"
        title = f"CVE {cve_id} on {target_id} (CVSS {cve.get('cvss')})"
        body = (
            f"Software: {cve.get('software')} {cve.get('version')}\n"
            f"{(cve.get('description') or '').strip()[:400]}"
        )
        event = proactive_events.make_event(
            kind="security_cve",
            severity=bus_severity,
            title=title,
            body=body,
            fingerprint_seed=f"cve:{cve_id}:{target_id}",
            context={
                "cve_id": cve_id,
                "cvss": cve.get("cvss"),
                "target_id": target_id,
                "software": cve.get("software"),
                "version": cve.get("version"),
            },
        )
        return proactive_events.publish(event)
    except Exception as exc:
        logger.warning("[CVE] publish event failed: %s", exc)
        return False


def _run_cve_sentinel(*, cycle_id: int, dry_run: bool) -> Dict[str, int]:
    """Scan Proxmox + VMs for CVEs, persist + alert. Returns counts dict.

    Kill-switched by ``KURO_CVE_SENTINEL_ENABLED``; CVSS floor via
    ``KURO_CVE_MIN_CVSS``; alert cap via ``KURO_CVE_MAX_ALERTS_PER_CYCLE``.
    """
    counts = {"cves": 0, "persisted": 0, "notified": 0}
    if not _env_bool(_ENV_CVE_ENABLED, True):
        logger.info("[CVE] sentinel disabled via %s", _ENV_CVE_ENABLED)
        return counts

    # HUD ticker: announce the sweep, then always settle back to IDLE/ALERT
    # in the finally block so a crashed scan never strands the HUD.
    try:
        from kuro_backend import dashboard_broadcast
        dashboard_broadcast.schedule_ui_command(
            "STATUS_TICKER",
            {"status": "SCANNING", "source": "CVE"},
        )
    except Exception:
        dashboard_broadcast = None  # type: ignore

    min_cvss = _env_float(_ENV_CVE_MIN_CVSS, 7.0)
    max_alerts = _env_int(_ENV_CVE_MAX_ALERTS, 5)
    max_cves_per_target = max(1, max_alerts)

    try:
        targets, cves = _cve_scan_via_openclaw(
            min_cvss=min_cvss, max_cves_per_target=max_cves_per_target,
        )
        source = "openclaw"
        if not cves:
            local_targets = _discover_proxmox_targets_locally()
            if local_targets:
                cves = _cve_scan_via_nvd_direct(
                    local_targets,
                    min_cvss=min_cvss,
                    max_cves_per_target=max_cves_per_target,
                )
                targets = local_targets
                source = "nvd_direct"
        if not cves:
            logger.info("[CVE] sentinel: no CVEs above CVSS %.1f", min_cvss)
            return counts

        counts["cves"] = len(cves)
        logger.info(
            "[CVE] sentinel source=%s targets=%d cves=%d (cap=%d)",
            source, len(targets), len(cves), max_alerts,
        )
        for cve in cves[:max_alerts]:
            if dry_run:
                logger.info("[CVE] dry_run cve=%s target=%s",
                            cve.get("id"), cve.get("target_id"))
                continue
            if _persist_cve_alert(cve, cycle_id=cycle_id):
                counts["persisted"] += 1
            if _publish_cve_event(cve):
                counts["notified"] += 1
        return counts
    finally:
        try:
            if dashboard_broadcast is not None:
                ticker_status = "ALERT" if counts["cves"] else "IDLE"
                detail = (
                    f"{counts['cves']} CVE" + ("s" if counts["cves"] != 1 else "")
                    if counts["cves"] else ""
                )
                dashboard_broadcast.schedule_ui_command(
                    "STATUS_TICKER",
                    {"status": ticker_status, "source": "CVE", "detail": detail},
                )
        except Exception:
            pass


def _summarize_search_results(finding: Finding, results: List[Dict[str, Any]]) -> str:
    """Ask Gemini to summarize search hits into 2-3 tight bullets."""
    if not results:
        return ""
    try:
        from google.genai import types as genai_types
        from kuro_backend.config import PRIMARY_MODEL
        from kuro_backend.memory_coordinator import _get_summary_genai_client

        client = _get_summary_genai_client()
        hits_blob = "\n".join(
            f"- {r.get('title', '')}: {r.get('snippet', '')} ({r.get('link', '')})"
            for r in results[:5]
        )
        prompt = (
            f"Temuan: {finding.description}\n"
            f"Kind: {finding.kind}\n"
            f"Hasil pencarian:\n{hits_blob}\n\n"
            "Ringkas dalam 2-3 bullet padat Bahasa Indonesia. Sertakan nama "
            "sumber/link yang paling relevan. JANGAN menambah fakta yang "
            "tidak muncul di hasil pencarian."
        )
        response = client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                top_p=0.1,
                top_k=1,
                max_output_tokens=256,
            ),
        )
        return (getattr(response, "text", "") or "").strip()[:1500]
    except Exception as exc:
        logger.warning("[DREAMING] summarize search failed: %s", exc)
        return ""


def _persist_dream_insight(
    finding: Finding,
    summary_text: str,
    *,
    source_label: str,
    cycle_id: int,
) -> bool:
    """Write the dream-insight into Chroma Layer 2 with a #dream-insight tag."""
    if not summary_text:
        return False
    try:
        from kuro_backend import memory_manager

        content = (
            f"[DREAM-INSIGHT] {finding.description}\n\n"
            f"Kind: {finding.kind} | Persona: {finding.persona_scope} | "
            f"Confidence: {finding.confidence:.2f} | Source: {source_label}\n\n"
            f"{summary_text}"
        )
        memory_manager.add_long_term_v2(
            content,
            metadata={
                "source": "dream_insight",
                "tag": "dream-insight",
                "persona_scope": finding.persona_scope,
                "finding_kind": finding.kind,
                "finding_id": finding.id,
                "cycle_id": cycle_id,
                "search_source": source_label,
            },
        )
        return True
    except Exception as exc:
        logger.warning("[DREAMING] chroma write failed finding=%s: %s", finding.id, exc)
        return False


def _enrich_finding(finding: Finding, *, cycle_id: int, dry_run: bool) -> bool:
    """Run search + summarize + persist. Returns True when Chroma was written."""
    if not _env_bool(_ENV_SEARCH, True):
        logger.info("[DREAMING] enrichment disabled via env")
        return False
    query = finding.search_query or finding.description
    if not query:
        return False
    results, source_label = _search_with_fallback(query)
    if not results:
        logger.info(
            "[DREAMING] no search results finding=%s query=%.80s",
            finding.id, query,
        )
        return False
    summary = _summarize_search_results(finding, results)
    if not summary:
        return False
    if dry_run:
        logger.info(
            "[DREAMING] dry_run enrich finding=%s source=%s summary=%.120s",
            finding.id, source_label, summary,
        )
        return False
    return _persist_dream_insight(
        finding, summary, source_label=source_label, cycle_id=cycle_id,
    )


# ---------------------------------------------------------------------------
# SSoT bump gating
# ---------------------------------------------------------------------------

def _maybe_bump_ssot(finding: Finding, *, cycle_id: int, dry_run: bool) -> bool:
    """Bump data revision only when the finding clears all gates."""
    if not finding.ssot_bump_recommended:
        return False
    if finding.kind not in ("inconsistency", "deep_research"):
        return False
    if finding.confidence < 0.5:
        return False
    if dry_run:
        logger.info(
            "[DREAMING] dry_run ssot_bump finding=%s persona=%s",
            finding.id, finding.persona_scope,
        )
        return False
    try:
        from kuro_backend.services import core_service
        core_service.bump_data_revision()
        logger.info(
            "[DREAMING] ssot bumped cycle=%d finding=%s persona=%s",
            cycle_id, finding.id, finding.persona_scope,
        )
        return True
    except Exception as exc:
        logger.warning("[DREAMING] ssot bump failed finding=%s: %s", finding.id, exc)
        return False


# ---------------------------------------------------------------------------
# Proactive Telegram notification (inconsistency-only + dedup)
# ---------------------------------------------------------------------------

def _finding_fingerprint(finding: Finding) -> str:
    seed = f"{finding.persona_scope}|{finding.kind}|{finding.description[:240]}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def _short_desc(finding: Finding, *, max_chars: int = 220) -> str:
    desc = finding.description.strip()
    if not desc:
        return ""
    if finding.suggested_fix:
        desc = f"{desc} Saran: {finding.suggested_fix}"
    if len(desc) > max_chars:
        desc = desc[: max_chars - 3] + "..."
    return desc


def _maybe_notify(finding: Finding, *, dry_run: bool) -> bool:
    """Send Telegram alert only for inconsistency findings; dedup by fingerprint."""
    if finding.kind != "inconsistency":
        return False
    from kuro_backend import memory_manager
    from kuro_backend import telegram_notifier

    fingerprint = _finding_fingerprint(finding)
    if memory_manager.dream_notification_seen(fingerprint):
        logger.info("[DREAMING] notify skipped (dedup) finding=%s", finding.id)
        return False
    sent = telegram_notifier.send_dream_inconsistency(
        finding.persona_scope,
        _short_desc(finding),
        finding_id=finding.id,
        dry_run=dry_run,
    )
    if sent and not dry_run:
        memory_manager.mark_dream_notification(
            fingerprint, finding.persona_scope, finding.kind,
        )
    return sent


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _idle_gate_passes(idle_min: int) -> bool:
    """Return True when the system looks idle (last interaction too old)."""
    from kuro_backend import memory_manager

    latest = memory_manager.query_short_term_latest_timestamp()
    if not latest:
        return True
    try:
        last_ts = datetime.fromisoformat(str(latest).replace(" ", "T"))
    except ValueError:
        return True
    delta = datetime.now() - last_ts
    return delta >= timedelta(minutes=max(1, int(idle_min)))


def _make_lease_holder() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def run_dreaming_cycle(
    *,
    lookback_hours: Optional[int] = None,
    dry_run: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """Main entry point. Safe to call from APScheduler or CLI.

    Returns an audit dict:
      ``{status, findings, enriched, notified, ssot_bumps, duration_ms, cycle_id}``
    """
    started = time.perf_counter()
    audit: Dict[str, Any] = {
        "status": "unknown",
        "findings": 0,
        "enriched": 0,
        "notified": 0,
        "ssot_bumps": 0,
        "cycle_id": None,
        "duration_ms": 0.0,
    }

    if not _env_bool(_ENV_ENABLED, True):
        audit["status"] = "disabled"
        audit["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return audit

    # Ensure schema is present. init_short_term_db is idempotent.
    try:
        from kuro_backend import memory_manager
        memory_manager.init_short_term_db()
    except Exception as exc:
        logger.error("[DREAMING] init failed: %s", exc)
        audit["status"] = "error"
        audit["error"] = str(exc)
        audit["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return audit

    lease_holder = _make_lease_holder()
    if not memory_manager.acquire_dreaming_lease(_LEASE_NAME, lease_holder, _LEASE_TTL_S):
        logger.info("[DREAMING] skipped — another holder owns the lease")
        audit["status"] = "skipped"
        audit["reason"] = "lease_held"
        audit["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return audit

    cycle_id = memory_manager.insert_dreaming_cycle(status="running")
    audit["cycle_id"] = cycle_id
    findings_count = 0
    enriched_count = 0
    notified_count = 0
    ssot_bumps = 0
    error_text: Optional[str] = None
    final_status = "ok"

    try:
        if not force and not _idle_gate_passes(_env_int(_ENV_IDLE_MIN, 20)):
            logger.info("[DREAMING] skipped — idle gate not cleared")
            audit["status"] = "skipped"
            audit["reason"] = "not_idle"
            final_status = "skipped"
            return audit

        # CVE sentinel is independent of the chat corpus — run it first so
        # a quiet conversation day still gets a nightly security check.
        try:
            cve_counts = _run_cve_sentinel(cycle_id=cycle_id, dry_run=dry_run)
        except Exception as cve_exc:
            logger.warning("[DREAMING] cve sentinel failed: %s", cve_exc)
            cve_counts = {"cves": 0, "persisted": 0, "notified": 0}
        audit["cve_findings"] = cve_counts.get("cves", 0)
        audit["cve_persisted"] = cve_counts.get("persisted", 0)
        audit["cve_notified"] = cve_counts.get("notified", 0)
        notified_count += cve_counts.get("notified", 0)

        hours = lookback_hours if lookback_hours is not None else _env_int(_ENV_LOOKBACK, 24)
        corpus = collect_last_24h(hours)
        if not corpus.get("summaries") and not corpus.get("ledger"):
            logger.info("[DREAMING] empty corpus (last %dh) — reflection skipped", hours)
            audit["status"] = "ok"
            audit["notified"] = notified_count
            return audit

        findings, overall_risk = _run_reflection(corpus)
        audit["overall_risk"] = overall_risk
        max_findings = _env_int(_ENV_MAX_FINDINGS, 8)
        findings = findings[:max_findings]
        findings_count = len(findings)
        audit["findings"] = findings_count

        confidence_threshold = _env_float(_ENV_CONF, 0.7)
        for finding in findings:
            logger.info(
                "[DREAMING] finding id=%s kind=%s persona=%s conf=%.2f",
                finding.id, finding.kind, finding.persona_scope, finding.confidence,
            )
            if finding.confidence < confidence_threshold:
                if _enrich_finding(finding, cycle_id=cycle_id, dry_run=dry_run):
                    enriched_count += 1
            if _maybe_bump_ssot(finding, cycle_id=cycle_id, dry_run=dry_run):
                ssot_bumps += 1
            if _maybe_notify(finding, dry_run=dry_run):
                notified_count += 1

        audit["enriched"] = enriched_count
        audit["notified"] = notified_count
        audit["ssot_bumps"] = ssot_bumps
        audit["status"] = "ok"
    except Exception as exc:
        logger.exception("[DREAMING] cycle failed: %s", exc)
        error_text = str(exc)
        final_status = "error"
        audit["status"] = "error"
        audit["error"] = error_text
    finally:
        try:
            memory_manager.update_dreaming_cycle(
                cycle_id,
                status=audit.get("status") or final_status,
                findings_count=findings_count,
                enriched_count=enriched_count,
                notified_count=notified_count,
                error=error_text,
            )
        except Exception as exc:
            logger.warning("[DREAMING] cycle audit update failed: %s", exc)
        try:
            memory_manager.release_dreaming_lease(_LEASE_NAME, lease_holder)
        except Exception as exc:
            logger.warning("[DREAMING] lease release failed: %s", exc)
        audit["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)

    return audit


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Kuro AI V6.0 Sovereign - Autonomous Memory Dreaming worker",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run the full pipeline but skip Chroma writes, Telegram, and SSoT bumps.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the idle gate (run even when Master was recently active).",
    )
    parser.add_argument(
        "--lookback-hours", type=int, default=None,
        help="Override KURO_DREAMING_LOOKBACK_HOURS for this invocation.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging to stderr (DEBUG level).",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_cli_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    audit = run_dreaming_cycle(
        lookback_hours=args.lookback_hours,
        dry_run=args.dry_run,
        force=args.force,
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2, default=str))
    return 0 if audit.get("status") in ("ok", "skipped", "disabled") else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "Finding",
    "collect_last_24h",
    "run_dreaming_cycle",
]
