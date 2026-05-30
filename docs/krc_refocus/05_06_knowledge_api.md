# KRC Refocus Phases 5-6 Approved Knowledge API

KRC now owns a separate approved knowledge gateway for KKG/KS.

## Routes

- `GET /api/knowledge/health`
- `POST /api/knowledge/search-approved`
- `POST /api/knowledge/context-approved`
- `POST /api/knowledge/candidates`
- `GET /api/knowledge/sources/{source_id}`
- `GET /api/admin/knowledge/candidates`
- `POST /api/admin/knowledge/candidates/{candidate_id}/approve`
- `POST /api/admin/knowledge/candidates/{candidate_id}/reject`

## Safety Contract

- Search/context/source routes require either existing KRC cookie auth or
  `KURO_KNOWLEDGE_API_KEY` via `X-Kuro-Knowledge-Key`.
- Candidate writes are disabled unless
  `KURO_KRC_KNOWLEDGE_CANDIDATES_ENABLED=true`.
- Candidate submission creates `pending` knowledge only.
- Admin approval is required before a candidate becomes approved knowledge.
- Responses redact secrets, filesystem paths, and database filenames.
- The API reads the KRC-owned `KURO_KNOWLEDGE_DB_PATH` SQLite store and does
  not expose raw chat history or raw database rows.

## Rollback

Leave `KURO_KRC_KNOWLEDGE_CANDIDATES_ENABLED=false` to keep the gateway
read-only. Remove `KURO_KNOWLEDGE_API_KEY` to require normal KRC login cookies.
