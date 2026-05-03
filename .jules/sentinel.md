## 2026-05-03 - [CRITICAL] Fix API Endpoint Authentication Bypass Vulnerability
**Vulnerability:** Multiple API endpoints in `main.py` defaulted the active user to `ADMIN_USERNAME` or `"Pantronux"` if the JWT token validation failed (`user` was `None`).
**Learning:** This pattern allowed any unauthenticated user to interact with the API with full administrative privileges, leading to severe authorization bypasses. The logic explicitly checked `if user else ADMIN_USERNAME` instead of enforcing validation failures.
**Prevention:** Always explicitly raise an `HTTPException(status_code=401, detail="Unauthorized")` when `validate_token` fails. Never provide a default fallback to an administrative account.
