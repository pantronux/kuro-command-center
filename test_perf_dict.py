import time
import uuid

start = time.perf_counter()
for _ in range(10000):
    d = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
    d["id"] = uuid.uuid4()
print(f"Literal dict init: {time.perf_counter() - start:.4f}s")

empty_grid = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
start = time.perf_counter()
for _ in range(10000):
    d = empty_grid.copy()
    d["id"] = uuid.uuid4()
print(f".copy() dict init: {time.perf_counter() - start:.4f}s")
