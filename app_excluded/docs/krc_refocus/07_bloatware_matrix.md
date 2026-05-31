# KRC Refocus Phase 7 Bloatware Deactivation Matrix

| Module/Feature | Classification | KRC Action |
|---|---|---|
| Memory V3 | core | keep |
| Ingestion Center | core | keep |
| QA Playground | optional_legacy | hidden/disabled in KRC by default; enable only with explicit flag |
| Research Playground | core | keep |
| Evaluation | optional_admin | hidden in KRC by default; scheduler disabled |
| Export | research_support | keep for research sessions and Playground artifacts |
| Provider Registry | core | keep |
| Storage/Admin Health | admin_only | keep |
| Approved Knowledge API | core | keep read-only by default |
| Candidate Knowledge Review | admin_only | candidate writes disabled by default |
| Market V2 / Market Sentinel | optional | hide/disable unless KRC flag enables it |
| Telegram V2 / Telegram Center | ops_core | keep as server monitoring command center; market commands hidden by default |
| Tools V2 Agent Mode | optional/admin_only | disabled in KRC UI unless explicitly enabled |
| Task/Reminder V2 | move_to_ks | hidden in KRC composer by default |
| Daily proactive events | move_to_ks | scheduler disabled by default |
| Fitness | future_remove/hide | scheduler disabled by default |
| CVE/Dreaming jobs | optional research/security | disabled by default in KRC scheduler profile |
| OpenClaw bridge | optional controlled | keep admin/controlled paths; Telegram alert disabled by default |
| Frontend V2 refs | legacy_hidden | do not reintroduce |

No working module is deleted in this phase. KRC mode narrows visibility and
background execution through profile flags.
