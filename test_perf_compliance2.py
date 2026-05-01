import time
from kuro_backend.compliance_db import _get_connection

start = time.perf_counter()
for _ in range(100):
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM evidence_matrix WHERE standard = 'ISO27001'")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM evidence_matrix WHERE standard = 'ISO27001' AND status = 'compliant'")
    compliant = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM evidence_matrix WHERE standard = 'ISO27001' AND status = 'non_compliant'")
    non_compliant = cursor.fetchone()[0]
    conn.close()
print(f"Multiple COUNT(*) time: {time.perf_counter() - start:.4f}s")
