import time
import random

def old_count(updates):
    advisor_count = sum(1 for target, _ in updates if target == "advisor")
    consultant_count = sum(1 for target, _ in updates if target == "consultant")
    return advisor_count, consultant_count

def new_count(updates):
    advisor_count = 0
    consultant_count = 0
    for target, _ in updates:
        if target == "advisor":
            advisor_count += 1
        elif target == "consultant":
            consultant_count += 1
    return advisor_count, consultant_count

updates = [(random.choice(["advisor", "consultant"]), i) for i in range(1000)]

start = time.perf_counter()
for _ in range(10000):
    old_count(updates)
print(f"Old count: {time.perf_counter() - start:.4f}s")

start = time.perf_counter()
for _ in range(10000):
    new_count(updates)
print(f"New count: {time.perf_counter() - start:.4f}s")
