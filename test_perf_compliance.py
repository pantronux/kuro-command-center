import time
from kuro_backend.compliance_db import get_compliance_progress, add_evidence, update_evidence_status

for i in range(100):
    add_evidence(f"file_{i}.txt", f"/path/{i}", "cat", "ISO27001", "1.1")
    update_evidence_status(i + 1, "compliant" if i % 2 == 0 else "non_compliant")

start = time.perf_counter()
for _ in range(100):
    get_compliance_progress("ISO27001")
print(f"SUM(CASE WHEN...) time: {time.perf_counter() - start:.4f}s")
