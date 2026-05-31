# App Split Known Risks

- The split is logical, not a physical repo split.
- SQLite remains the default store for the new research and knowledge boundary.
- KCC is currently a shell over existing ops/admin endpoints, not a full custom operations console.
- Kuro Knowledge ingest jobs are registered safely, but parser/chunker/embedder worker extraction is still incremental.
- Existing legacy modules remain in the repo behind flags; cleanup should wait until role boundaries are stable.
- Browser trust/TLS for the existing `8443` route still depends on the current certificate setup.
- Full tenant-grade RBAC is not implemented; admin checks are still username-based in existing routes.
