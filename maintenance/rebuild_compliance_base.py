#!/usr/bin/env python3
"""
Kuro AI V3.1 - Compliance Knowledge Base Rebuild Script
========================================================

USAGE:
    python maintenance/rebuild_compliance_base.py [OPTIONS]

OPTIONS:
    --directory PATH    Path to compliance documents (default: /home/kuro/ComplianceDoc)
    --stats             Show current compliance database statistics only
    --clear             Clear existing compliance database before ingestion
    --dry-run           List files that would be processed without ingesting

SECURITY:
    - This script ONLY reads from the specified directory
    - Files are NEVER copied to the project directory
    - All processing happens in-memory or in dedicated ChromaDB

EXAMPLES:
    # Full rebuild with clear
    python maintenance/rebuild_compliance_base.py --clear

    # Check current stats
    python maintenance/rebuild_compliance_base.py --stats

    # Process specific directory
    python maintenance/rebuild_compliance_base.py --directory /home/kuro/ComplianceDoc
"""

import sys
import os
import argparse
import json
import time
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kuro_backend import memory_manager


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    try:
        payload = {
            "sessionId": "f653ac",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open("/home/kuro/projects/kuro/.cursor/debug-f653ac.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def preflight_dependency_check() -> bool:
    """
    Ensure local maintenance runtime has mandatory dependencies before ingest.
    This avoids noisy per-file failures when the script uses a different Python env.
    """
    missing = []
    try:
        import chromadb  # noqa: F401
    except Exception:
        missing.append("chromadb")

    try:
        import fitz  # noqa: F401
    except Exception:
        missing.append("PyMuPDF(fitz)")

    if not missing:
        # region agent log
        _debug_log(
            run_id="post_fix",
            hypothesis_id="H6",
            location="rebuild_compliance_base.py:preflight_dependency_check:ok",
            message="Dependency preflight passed",
            data={"python_executable": sys.executable},
        )
        # endregion
        return True

    print("[ERROR] Dependency preflight failed.")
    print(f"  Missing packages in current interpreter: {', '.join(missing)}")
    print(f"  Python executable: {sys.executable}")
    print("  Reason: maintenance script likely uses different environment from running API server.")
    print("  Action: activate the same virtualenv/runtime as API server, then rerun.")
    print("  Example:")
    print("    source .venv/bin/activate")
    print("    pip install chromadb PyMuPDF")
    # region agent log
    _debug_log(
        run_id="post_fix",
        hypothesis_id="H6",
        location="rebuild_compliance_base.py:preflight_dependency_check:failed",
        message="Dependency preflight failed",
        data={"missing": missing, "python_executable": sys.executable},
    )
    # endregion
    return False


def print_header():
    """Print script header."""
    print("=" * 70)
    print("Kuro AI V3.1 - Compliance Knowledge Base Rebuild")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


def show_stats():
    """Show current compliance database statistics."""
    print("[STATS] Current Compliance Knowledge Base:")
    print("-" * 40)
    
    stats = memory_manager.get_compliance_stats()
    
    if not stats.get("available"):
        print(f"  Status: Not available ({stats.get('reason', 'Unknown')})")
        return
    
    print(f"  Total Chunks: {stats.get('total_chunks', 0)}")
    print(f"  ISO Standards: {stats.get('standard_count', 0)}")
    
    if stats.get("iso_standards"):
        print("\n  Standards Indexed:")
        for iso in sorted(stats["iso_standards"]):
            print(f"    - {iso}")
    
    if stats.get("source_files"):
        print(f"\n  Source Files: {len(stats['source_files'])}")


def list_files(directory):
    """List PDF files in directory."""
    if not os.path.exists(directory):
        print(f"[ERROR] Directory not found: {directory}")
        return []
    
    pdf_files = []
    for f in os.listdir(directory):
        if f.lower().endswith('.pdf'):
            filepath = os.path.join(directory, f)
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            pdf_files.append({"name": f, "size_mb": size_mb})
    
    print(f"\n[FILES] Found {len(pdf_files)} PDF files in {directory}:")
    print("-" * 40)
    
    total_size = 0
    for f in sorted(pdf_files, key=lambda x: x["name"]):
        print(f"  {f['name']:<50} {f['size_mb']:.1f} MB")
        total_size += f["size_mb"]
    
    print(f"\n  Total: {total_size:.1f} MB")
    print()
    
    return pdf_files


def clear_database():
    """Clear existing compliance database."""
    print("[CLEAR] Clearing existing compliance database...")
    
    collection = memory_manager._get_compliance_collection()
    if collection is None:
        print("  [ERROR] Compliance ChromaDB not available")
        return False
    
    try:
        existing = collection.get()
        if existing and existing.get("ids"):
            collection.delete(ids=existing["ids"])
            print(f"  [OK] Deleted {len(existing['ids'])} existing chunks")
        else:
            print("  [OK] Database already empty")
        return True
    except Exception as e:
        print(f"  [ERROR] Failed to clear: {e}")
        return False


def rebuild(directory, clear_first=False):
    """Run full rebuild process."""
    print_header()
    
    # Show current stats
    show_stats()
    print()
    
    # List files to process
    pdf_files = list_files(directory)
    if not pdf_files:
        print("[ABORT] No PDF files found to process")
        return
    
    # Clear if requested
    if clear_first:
        if not clear_database():
            print("[ABORT] Failed to clear database")
            return
        print()
    
    # Run ingestion
    print("[INGEST] Starting batch ingestion...")
    print("-" * 40)
    
    result = memory_manager.ingest_compliance_base(directory)
    
    # Print results
    print()
    print("=" * 70)
    print("INGESTION RESULTS")
    print("=" * 70)
    
    if result.get("success"):
        print(f"  Status: SUCCESS")
        print(f"  Files Processed: {result['files_processed']}/{result['files_found']}")
        print(f"  Total Chunks: {result['total_chunks']}")
        print(f"  ISO Standards: {len(result['iso_standards'])}")
        
        if result.get("documents"):
            print("\n  Documents Indexed:")
            for doc in result["documents"]:
                print(f"    ✓ {doc['filename']}")
                print(f"      ISO: {doc['iso_name']}")
                print(f"      Chunks: {doc['chunks']}, Pages: {doc['pages']}")
                if doc.get("summary"):
                    print(f"      Summary: {doc['summary'][:100]}...")
                print()
        
        if result.get("errors"):
            print(f"\n  Errors ({len(result['errors'])}):")
            for err in result["errors"]:
                print(f"    ✗ {err['file']}: {err['error']}")
    else:
        print(f"  Status: FAILED")
        print(f"  Reason: {result.get('reason', 'Unknown')}")
    
    print()
    print("=" * 70)
    print("Rebuild complete!")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Kuro AI V3.1 - Compliance Knowledge Base Rebuild Script"
    )
    parser.add_argument(
        "--directory",
        default="/home/kuro/ComplianceDoc",
        help="Path to compliance documents (default: /home/kuro/ComplianceDoc)"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show current compliance database statistics only"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing compliance database before ingestion"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be processed without ingesting"
    )
    
    args = parser.parse_args()
    
    print_header()
    
    if args.stats:
        show_stats()
        return
    
    if args.dry_run:
        list_files(args.directory)
        return

    if not preflight_dependency_check():
        return
    
    rebuild(args.directory, args.clear)


if __name__ == "__main__":
    main()
