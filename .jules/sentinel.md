## 2024-05-18 - Admin Endpoint Broken Access Control
**Vulnerability:** Several sensitive administrative endpoints under `/api/persona/history/*` (used to rewrite database state, perform restores, and override logic) were missing explicit authorization checks, meaning any unauthenticated user could trigger them.
**Learning:** In FastAPI implementations where endpoints are added ad-hoc without global router dependencies, it's easy to forget to add authorization logic to specific routes, resulting in Broken Access Control vulnerabilities.
**Prevention:** For endpoints intended strictly for administrators, always inject the `request: Request` parameter and invoke the explicit authorization dependency `require_admin_user(request)` at the very beginning of the endpoint body.
## 2024-05-18 - Admin Endpoint Broken Access Control
**Vulnerability:** Several sensitive administrative endpoints (e.g. system status, health check, log storage, system analysis, memory re-indexing, index path generation) were missing explicit authorization checks, meaning any authenticated (or sometimes unauthenticated) user could access or trigger them.
**Learning:** In FastAPI implementations where endpoints are added ad-hoc without global router dependencies, it's easy to forget to add authorization logic to specific routes, resulting in Broken Access Control vulnerabilities.
**Prevention:** For endpoints intended strictly for administrators, always inject the `request: Request` parameter and invoke the explicit authorization dependency `require_admin_user(request)` at the very beginning of the endpoint body.
## 2026-05-18 - System Path Traversal in index_system_path
**Vulnerability:** The `index_system_path` function in `kuro_backend/tools/base_tools.py` accepted a `path` parameter and crawled the directory without verifying it was inside the allowed `WHITELIST_PATHS`, leading to a potential Path Traversal / Arbitrary File Read.
**Learning:** Security checks applied in high-level wrappers like `smart_read` or `universal_read` might be missed in other specialized system tools, leaving those paths vulnerable to traversal attacks.
**Prevention:** Implement boundary enforcement natively within any function processing raw file system paths by using `os.path.realpath` and `os.path.commonpath` to ensure the requested path is constrained to a trusted root directory.
