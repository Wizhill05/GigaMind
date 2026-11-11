Implementation status, 2026-11-11

The original audit is the full scope. This file records completion gaps, not a reduced release plan. No deployment or production data changes have been performed.

Reviewed and integrated foundations:
- Memory deletion/reset commits, logical-parent listing/statistics and category/source predicates.
- Credential hashing/revocation and REST admin isolation. Unsafe OAuth removed from service routes; replacement is still missing.
- Working authenticated stateless MCP SDK /mcp transport with real-client checks, scoped accepted-memory search/context, exact retrieval and evidence-backed proposal tools. Legacy profile tool remains admin-only.
- Proposal/evidence/revision core, explicit conflict supersession, SQL project isolation, DB uniqueness, concurrency tests, mountable and mounted review API.
- Versioned SQLite/PostgreSQL migration runner and readiness, verified with native isolated PostgreSQL/pgvector tests and local production-mode startup.
- Source-first legacy memory indexing, revision-safe chunk/vector replacement, failed-provider source retention and revision checks through REST/React edits.
- React auth gating, awaited saves/draft retention, filtered refresh, dialog focus, visible settings export/reset errors and 8 focused tests.

In flight:
- Proposal inbox/revision review UI correction for edited-text conflict preview and pending mutation handling.

Still required:
- Approved records are available through scoped context/MCP tools, but remain separate from legacy dashboard MemoryItem views; unified presentation and richer retrieval remain required.
- Handoffs, issue reporting, temporal validity/expiry and complete authenticated provenance through legacy admin CRUD.
- Working supported OAuth flow or concrete supported operator configuration, credential expiry/last use, input/upload bounds.
- Full corpus semantic/lexical retrieval, transcript segmentation including late turns, branch-aware unified imports and reliable no-match behavior.
- Durable import/index/reindex jobs with progress/retries; multimodal page limits and truthful index state; safe shared-attachment GC.
- Remaining UI API errors/cancellation/invalidation and component scenarios; credentials/activity/handoff/retrieval inspector screens.
- Full backup/restore, forgetting tombstones/import ledger, labeled isolated demo fixtures/evaluation, reproducible CI/deployment/docs and real multi-client acceptance/recovery checks.

Every agent change requires parent full-diff review and relevant local tests before acceptance. See implementation-review-log.md for findings and verification limits.
