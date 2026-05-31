# Kuro App Split Implementation Report

Tanggal: 2026-05-31
Branch kerja: `krc-kcc-knowledge-split`
Rollback tag: `before-krc-kcc-knowledge-split`
Target repo: `/home/kuro/projects/kuro`

## Ringkasan

Implementasi ini menjalankan split logical untuk keluarga aplikasi Kuro:

```text
KRC / Kuro Research Center = PhD research cockpit
KCC / Kuro Command Center  = operational control room
Kuro Knowledge             = approved knowledge, candidate, provenance, ingest boundary
Kuro Stack                 = daily chat app terpisah
```

Split ini belum memecah repo secara fisik. Semua perubahan dibuat additive,
role-based, dan reversible.

## Safety Baseline

Yang dibuat:

- Branch baru: `krc-kcc-knowledge-split`
- Tag rollback: `before-krc-kcc-knowledge-split`
- Backup runtime files ke `backups/pre-app-split/`
- Baseline doc: `docs/app_split/00_baseline.md`

Backup berisi 24 file runtime/env/DB/JSON penting, termasuk:

```text
.env
.env.example
.env.production.example
kuro_auth.db
kuro_chat_history.db
kuro_memory_v3.db
kuro_ingestion.db
kuro_market_v2.db
kuro_telegram_v2.db
master_profile.json
kuro_memory.json
phoenix_data/phoenix.db
```

Catatan penting:

- Tidak ada destructive migration.
- Tidak ada `git reset --hard`.
- Tidak ada penghapusan data runtime.
- `/home/kuro/projects/Kuro-UI-Prototype` tidak disentuh.

## App Role Layer

File baru:

- `kuro_backend/app_roles.py`

Fungsi utama:

- `get_app_role()`
- `is_krc_role()`
- `is_kcc_role()`
- `is_knowledge_role()`
- `is_dev_role()`
- `get_app_role_snapshot(public=False)`

Role yang didukung:

```text
legacy
krc
kcc
knowledge
dev
```

Kontrak:

- `KURO_APP_ROLE` adalah switch utama.
- `KURO_APP_PROFILE` tetap didukung untuk kompatibilitas.
- Jika keduanya ada, `KURO_APP_ROLE` menang.
- Default tetap `legacy`.

Route baru:

- `GET /api/admin/app-role`

Route ini admin-only dan tidak membocorkan secret.

## Env Example Files

File baru:

- `.env.krc.example`
- `.env.kcc.example`
- `.env.knowledge.example`

Isi utama:

- KRC memakai `KURO_APP_ROLE=krc`, port `8443`, persona lock `phd_advisor`, dan mematikan QA/market/Telegram/daily bloat secara default.
- KCC memakai `KURO_APP_ROLE=kcc`, port `8444`, dan mengaktifkan fitur operational.
- Knowledge memakai `KURO_APP_ROLE=knowledge`, port `8088`, dan candidate write default off.

## KRC Officialization

File yang diubah:

- `main.py`
- `web_interface/templates/krc_shell.html`
- `web_interface/static/js/krc_shell.js`

Route behavior:

- `/krc-shell` tetap dipertahankan sebagai compatibility route.
- `/research` ditambahkan sebagai alias KRC.
- `/` redirect ke `/research` saat `KURO_APP_ROLE=krc`.
- KRC shell otomatis aktif dalam role `krc`.
- `knowledge` dan `kcc` role tidak melayani KRC shell.

UI/copy yang diganti:

- Dari prototype/playground wording menjadi official KRC wording.
- Brand subtitle menjadi `PhD Research Workspace`.
- Persona indicator menjadi `PhD Advisor`.
- Composer placeholder menjadi `Message Kuro PhD Advisor...`.
- Welcome panel diarahkan ke literature, research questions, novelty gap, argument map, dan runtime research.

KRC default sekarang menyembunyikan:

- Legacy Chat
- QA Playground
- Market Sentinel
- Telegram Command Center
- Daily/task/proactive surfaces

Flag untuk menampilkan legacy chat jika benar-benar perlu:

```env
KURO_KRC_LEGACY_CHAT_VISIBLE=true
```

## PhD Advisor Persona Lock

File baru:

- `kuro_backend/krc_advisor.py`

File yang diubah:

- `main.py`
- `kuro_backend/memory_manager.py`
- `kuro_backend/personas.py`
- `web_interface/static/js/krc_shell.js`

Persona baru:

```text
phd_advisor
```

KRC behavior:

- Semua chat/session request di KRC dipaksa ke `phd_advisor`.
- Persona mutation endpoint di KRC tidak mengubah persona.
- Legacy/dev tetap mempertahankan behavior persona lama.

Prompt rule:

- Tidak mengaku sebagai orang nyata.
- Tidak impersonate professor nyata.
- Fokus software engineering, modelling, ontology, knowledge representation, reasoning, methodology.
- Wajib memisahkan fact, evidence, inference, speculation.
- Tidak boleh mengarang paper title, citation, author, venue, atau claim.

## KRC Research Data Model

Package baru:

```text
kuro_backend/research_center/
├── __init__.py
├── advisor_prompt.py
├── db.py
├── exports.py
├── routes.py
├── schemas.py
└── service.py
```

SQLite table additive:

```text
research_projects
paper_sources
research_notes
research_claims
research_questions
novelty_gaps
argument_nodes
argument_edges
advisor_sessions
```

Route baru:

```text
GET  /api/research/projects
POST /api/research/projects
GET  /api/research/projects/{project_id}
PATCH /api/research/projects/{project_id}

POST /api/research/sources
GET  /api/research/sources
GET  /api/research/sources/{source_id}

POST /api/research/claims
GET  /api/research/claims

POST /api/research/questions
GET  /api/research/questions

POST /api/research/novelty-gaps
GET  /api/research/novelty-gaps

POST /api/research/argument-map/nodes
POST /api/research/argument-map/edges
GET  /api/research/argument-map

POST /api/research/ingest
```

Security behavior:

- Semua `/api/research/*` butuh auth.
- Owner isolation diterapkan lewat `owner_username`.
- User lain tidak bisa membaca project milik user berbeda.

## Kuro Knowledge Boundary

File yang diubah:

- `kuro_backend/knowledge_center/candidates.py`
- `kuro_backend/knowledge_center/routes.py`
- `kuro_backend/knowledge_center/schemas.py`
- `kuro_backend/knowledge_center/policy.py`

Yang sudah ada dan dipertahankan:

- Approved knowledge search
- Approved context
- Candidate submission/review
- Redaction
- Audit logging
- Source metadata endpoint

Yang ditambahkan:

```text
knowledge_ingest_jobs table
POST /api/knowledge/ingest
GET  /api/knowledge/ingest/jobs
GET  /api/knowledge/ingest/jobs/{job_id}
POST /api/knowledge/ingest/jobs/{job_id}/retry
```

Safety behavior:

- Candidate writes tetap default off.
- Search-approved tidak mengembalikan raw `content`.
- Redaction tetap membersihkan path, DB file name, token/password/API key style text.
- Retry ingest job admin-only.

## Ingestion Boundary

Keputusan implementasi:

```text
Kuro Knowledge = engine/job owner
KRC            = research ingest workflow
KCC            = ingestion ops/admin
Kuro Stack     = candidate submit only if enabled
```

Route KRC:

```text
POST /api/research/ingest
```

Behavior:

- Membuat `PaperSource` di KRC.
- Membuat ingest job di Kuro Knowledge.
- Menghubungkan metadata `research_project_id` dan `research_source_id`.

## Kuro Command Center

File baru:

- `web_interface/templates/command_center.html`

Route baru:

```text
GET /command-center
```

Behavior:

- Hanya aktif saat `KURO_APP_ROLE=kcc` atau `dev`.
- Non-admin ditolak.
- `/` redirect ke `/command-center` saat `KURO_APP_ROLE=kcc`.

Module yang ditampilkan:

- Market Sentinel
- Telegram Command Center
- Ingestion Operations
- Runtime Registry
- Storage Health
- Memory Health
- Feature Flags
- Observability

KCC sengaja tidak menampilkan literature/research-only UI.

## Kuro Stack Integration Contract

File baru:

- `docs/integrations/kuro_stack_contract.md`
- `kuro_backend/integrations/__init__.py`
- `kuro_backend/integrations/kuro_stack_client.py`

Contract:

- Kuro Stack hanya bicara ke Kuro Knowledge via HTTP API.
- Tidak boleh direct DB sharing.
- Tidak boleh baca raw KRC chat history.
- Tidak boleh direct canonical write ke research memory.

Client helper:

- `search_approved()`
- `context_approved()`
- `submit_candidate()`

## Scheduler Split

File yang diubah:

- `kuro_backend/krc_profile.py`

Default KRC:

- Backup enabled
- Memory decay enabled
- File retention enabled
- Market disabled
- Telegram disabled
- Daily briefing disabled
- Proactive disabled
- Fitness disabled

KCC role:

- Backup enabled
- Market enabled
- Telegram enabled
- Daily briefing tetap disabled

Knowledge role:

- File retention enabled
- Market/Telegram disabled

Legacy behavior tetap kompatibel.

## Deployment Examples

File baru:

```text
deploy/systemd/kuro-research-center.service.example
deploy/systemd/kuro-command-center.service.example
deploy/systemd/kuro-knowledge.service.example
deploy/nginx/kuro-apps.conf.example
docs/deployment/app_split_same_vm.md
```

Port target:

```text
KRC       8443
KCC       8444
Knowledge 8088
Stack     owned by /home/kuro/projects/kuro-stack
```

Compatibility:

```text
/krc-shell tetap dipertahankan
/research jadi alias masa depan
```

## Documentation

File baru:

```text
docs/app_split/00_baseline.md
docs/app_split/README.md
docs/app_split/final_acceptance.md
docs/app_split/rollback.md
docs/app_split/known_risks.md
docs/app_split/implementation_report.md
docs/integrations/kuro_stack_contract.md
docs/deployment/app_split_same_vm.md
```

File yang diupdate:

```text
SYSTEM_MAP.md
```

SYSTEM_MAP sekarang mendokumentasikan:

- `KURO_APP_ROLE`
- KRC/KCC/Kuro Knowledge/Kuro Stack split
- `phd_advisor`
- KRC research routes
- KCC route
- Kuro Knowledge ingest APIs
- Scheduler split
- Rollback behavior

## Tests

File test baru:

```text
tests/test_app_roles.py
tests/test_krc_phd_advisor_lock.py
tests/test_krc_research_routes.py
tests/test_krc_shell_officialization.py
tests/test_kcc_role_routes.py
tests/test_knowledge_service_role.py
tests/test_ingestion_boundary.py
tests/test_scheduler_role_split.py
tests/test_stack_knowledge_contract.py
tests/test_app_split_security.py
```

File test yang diupdate:

```text
tests/conftest.py
tests/test_krc_advisor_persona_lock.py
tests/test_krc_navigation_profile.py
tests/test_krc_profile_flags.py
tests/test_krc_scheduler_flags.py
tests/test_krc_shell.py
tests/test_krc_system_map_docs.py
```

Verification yang dijalankan:

```bash
python3 -m compileall kuro_backend main.py
pytest tests/ -x --tb=short
```

Hasil:

```text
compileall passed
668 passed, 230 warnings in 318.98s
```

Optional lint:

```bash
ruff check .
```

Hasil:

```text
ruff tidak tersedia di PATH
```

Tidak ada install dependency yang diperlukan selama run ini.

## File Yang Perlu Dibedakan

Sebelum app split dimulai, working tree sudah punya perubahan di beberapa file:

```text
kuro_backend/chat_history.py
kuro_backend/export_engine/exporters/*.py
test_grand_auditor.py
kuro_backend/export_engine/exporters/attachment_format.py
node_modules/
```

Saya tidak melakukan revert terhadap file-file tersebut karena itu terlihat
sebagai pekerjaan yang sudah ada sebelumnya. Status git masih menampilkan
file-file itu sebagai dirty/untracked.

## Rollback

Rollback environment:

```env
KURO_APP_ROLE=legacy
KURO_APP_PROFILE=legacy
KURO_KRC_SHELL_ENABLED=false
```

Rollback git:

```bash
git switch main
git reset --hard before-krc-kcc-knowledge-split
```

Rollback data:

```text
backups/pre-app-split/
```

## Deferred Work

Hal yang sengaja belum dipaksakan di tahap ini:

- Physical repo split KRC/KCC/Knowledge.
- Full custom KCC dashboard beyond operational shell.
- Full ingest parser/chunker/embedder extraction worker.
- Strong tenant-grade RBAC/SSO.
- PostgreSQL/pgvector migration.
- Production TLS cleanup.
- Browser smoke test via Playwright untuk UI shell.

## Final State

Current logical target state:

```text
KRC = PhD research cockpit with one PhD Advisor
KCC = operational admin/control system
Kuro Knowledge = knowledge/ingest/memory gateway
Kuro Stack = daily chat assistant, separate app
```

The implementation is additive, tested, and reversible.
