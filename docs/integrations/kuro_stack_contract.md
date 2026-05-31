# Kuro Stack Knowledge Contract

Kuro Stack talks to Kuro Knowledge through HTTP APIs only.

Allowed:

- `POST /api/knowledge/search-approved`
- `POST /api/knowledge/context-approved`
- `POST /api/knowledge/candidates` when candidate submission is explicitly enabled

Forbidden:

- Direct reads of KRC chat history
- Direct writes to canonical research memory
- Shared SQLite DB access
- Raw file path or secret exchange

Default flags:

```env
KURO_STACK_KNOWLEDGE_GATEWAY_URL=http://127.0.0.1:8550
KURO_STACK_APPROVED_KNOWLEDGE_READ_ENABLED=true
KURO_STACK_CANDIDATE_SUBMIT_ENABLED=false
```

Kuro Knowledge redacts outbound context and returns approved knowledge only by default.
