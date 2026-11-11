Implementation status, 2026-11-11

The original audit is the full scope. This file records completion gaps, not a reduced release plan. No deployment or production data changes have been performed.

Reviewed and integrated foundations:
- Memory deletion/reset commits, logical-parent listing/statistics and category/source predicates.
- Credential hashing/revocation and REST admin isolation. External RS256 OAuth resource authorization with persistent local bindings, scope intersection, discovery and signed-token SDK checks; external issuer configuration is documented. Local token issuance stays disabled.
- Working authenticated stateless MCP SDK /mcp transport with real-client checks, scoped accepted-memory search/context, exact retrieval and evidence-backed proposal tools. Legacy profile tool remains admin-only.
- Proposal/evidence/revision core, explicit conflict supersession, SQL project isolation, DB uniqueness, concurrency tests, mountable and mounted review API.
- Versioned SQLite/PostgreSQL migration runner and readiness, verified with native isolated PostgreSQL/pgvector tests and local production-mode startup.
- Source-first legacy memory indexing, revision-safe chunk/vector replacement, failed-provider source retention and revision checks through REST/React edits.
- React auth gating, awaited saves/draft retention, filtered refresh, dialog focus and visible settings export/reset errors. Proposal inbox/revision review with edited-content conflict previews, explicit supersession, retry and restore behavior; 18 focused frontend tests pass.

Additional reviewed foundations:
- Durable queue core with lease fencing, retry/reclaim and real indexing cancellation tests; native PostgreSQL claim/idempotency checks. Atomic file metadata/chunk/vector publication is verified with injected native failures.
- Isolated synthetic demo CLI with 64 source memories, 15 conversations, scoped reviewed facts/rules and pending proposals; source indexes stay pending.
- Canonical branch-aware CLI/REST source imports, atomic deduplication, complete text/role retention and no automatic promotion to facts or provider requirement. Segmentation/indexing and full provenance ledger remain unfinished.

In flight:
- Queue HTTP/worker startup integration, full-transcript lexical retrieval and missing authentication/memory component scenarios. React auth/list implementation is intermediate pending those behavior checks.

Still required:
- Approved records are available through scoped context/MCP tools, but remain separate from legacy dashboard MemoryItem views; unified presentation and richer retrieval remain required.
- Handoffs, issue reporting, temporal validity/expiry and complete authenticated provenance through legacy admin CRUD.
- External-provider interoperability acceptance, credential expiry/last use and input/upload bounds. Supported JWT issuer configuration is documented; no hosted issuer was provisioned or tested.
- Full corpus semantic/lexical retrieval, transcript segmentation including late turns, branch-aware unified imports and reliable no-match behavior.
- Durable import/index/reindex jobs with progress/retries; multimodal page limits and truthful index state; safe shared-attachment GC.
- Remaining UI API errors/cancellation/invalidation and component scenarios; credentials/activity/handoff/retrieval inspector screens.
- Full backup/restore, forgetting tombstones/import ledger, labeled isolated demo fixtures/evaluation, reproducible CI/deployment/docs and real multi-client acceptance/recovery checks.

Every agent change requires parent full-diff review and relevant local tests before acceptance. See implementation-review-log.md for findings and verification limits.
