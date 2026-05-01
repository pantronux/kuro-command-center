import time
_EMPTY_SUMMARY_JSON = {
    "topic": "",
    "decisions": [],
    "open_questions": [],
    "entities": [],
    "novelty_points": [],
    "technical_specs": [],
    "compliance_refs": [],
    "tone_markers": [],
}
start = time.perf_counter()
for _ in range(100000):
    out = {k: v for k, v in _EMPTY_SUMMARY_JSON.items()}
print(f"Dict comprehension init: {time.perf_counter() - start:.4f}s")

start = time.perf_counter()
for _ in range(100000):
    out = _EMPTY_SUMMARY_JSON.copy()
print(f".copy() init: {time.perf_counter() - start:.4f}s")
