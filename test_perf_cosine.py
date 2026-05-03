import time
import math
import random
from typing import Iterable

def _cosine_old(a: Iterable[float], b: Iterable[float]) -> float:
    ax = list(a)
    bx = list(b)
    if not ax or not bx or len(ax) != len(bx):
        return 0.0

    num = 0.0
    da_sq = 0.0
    db_sq = 0.0
    for x, y in zip(ax, bx):
        num += x * y
        da_sq += x * x
        db_sq += y * y

    if da_sq == 0 or db_sq == 0:
        return 0.0
    return num / math.sqrt(da_sq * db_sq)

def _cosine_new(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0

    num = 0.0
    da_sq = 0.0
    db_sq = 0.0
    for x, y in zip(a, b):
        num += x * y
        da_sq += x * x
        db_sq += y * y

    if da_sq == 0 or db_sq == 0:
        return 0.0
    return num / math.sqrt(da_sq * db_sq)

vec_a = tuple(random.random() for _ in range(768))
vec_b = tuple(random.random() for _ in range(768))

start = time.perf_counter()
for _ in range(10000):
    _cosine_old(vec_a, vec_b)
print(f"Old _cosine: {time.perf_counter() - start:.4f}s")

start = time.perf_counter()
for _ in range(10000):
    _cosine_new(vec_a, vec_b)
print(f"New _cosine: {time.perf_counter() - start:.4f}s")
