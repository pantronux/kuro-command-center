import time
import asyncio
from kuro_backend.services.core_service import init_all_databases, get_reminder_history, get_monthly_data

init_all_databases()

start = time.perf_counter()
get_reminder_history(50)
print(f"get_reminder_history(50): {time.perf_counter() - start:.4f}s")

start = time.perf_counter()
get_monthly_data(2026, 4)
print(f"get_monthly_data(2026, 4): {time.perf_counter() - start:.4f}s")
