#!/usr/bin/env python3
"""Smoke test for Mem0 store path (string + dict payloads)."""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    try:
        from kuro_backend.perpetual_memory import perpetual_memory
    except Exception as e:
        log.error("Import failed: %s", e)
        return 1

    pm = perpetual_memory
    if not pm.client:
        log.error("Mem0 client unavailable (check API key / mem0 installation).")
        return 1

    # Mixed payload shape to validate robustness and type handling.
    memories = [
        f"SMOKE_MEM0_STR {datetime.now().isoformat()}",
        {
            "text": f"SMOKE_MEM0_DICT {datetime.now().isoformat()}",
            "metadata": {
                "type": "smoke_test",
                "nested": {"ok": True, "at": datetime.now()},  # datetime should be serialized
                "pid": os.getpid(),
            },
        },
    ]

    pm.store_memories(memories)
    log.info("smoke_mem0_store: invoked store_memories for %s items", len(memories))
    log.info("Expect log lines: [MEM0] Memory successfully stored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
