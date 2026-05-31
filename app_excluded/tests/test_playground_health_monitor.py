from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


spec = spec_from_file_location(
    "health_monitor_module", Path("playground_runtime/providers/health_monitor.py")
)
module = module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)
HealthMonitor = module.HealthMonitor


def test_cooldown_expiry_resets_failure_counter():
    monitor = HealthMonitor(failure_threshold=2, cooldown_seconds=60)

    monitor.record_failure("gemini")
    monitor.record_failure("gemini")
    state = monitor._state("gemini")
    assert state.consecutive_failures == 2
    assert not monitor.is_available("gemini")

    state.unavailable_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert monitor.is_available("gemini")
    assert state.consecutive_failures == 0

    monitor.record_failure("gemini")
    assert monitor.is_available("gemini")
