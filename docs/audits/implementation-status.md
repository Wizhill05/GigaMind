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

Additional reviewed integration:
- Admin jobs API and standalone worker, controlled graceful shutdown/renewal and native clean startup. Automatic source pipelines remain unfinished. Current-resource ownership and durable tombstones now fence stale publishers and block re-enqueue after forgetting, with native concurrency checks.
- Auth/list race, deletion and activity behavior verified in 36 frontend tests; production build passes. Client expiry, throttled last use, atomic rotation/revocation and v2 legacy migration are verified, including native races.
- Full decoded transcript lexical search without a provider, optional existing vector candidates with SQL prefilters, source snippets and native search checks.
- MIME-safe text/image embedding requests, all-page PDF anchors, stored-metadata reindex and strict provider-vector validation. Offline payload and native publication checks pass; live-provider OCR/token/relevance acceptance remains unfinished.

In flight:
- Durable upload registration, decoded-file validation, file job progress and remaining memory-engine features. Reference-safe cleanup, delete/reindex routes, tombstone access fencing, credential lifecycle and review activity are reviewed and integrated.

Still required:
- Approved records are available through scoped context/MCP tools, but remain separate from legacy dashboard MemoryItem views; unified presentation and richer retrieval remain required.
- Handoffs, issue reporting, temporal validity/expiry and complete authenticated provenance through legacy admin CRUD.
- External-provider interoperability acceptance and decoded-file upload bounds. Global encoded-body limits including MCP are implemented. Credential expiry/last-use/rotation are implemented; credential console is implemented. Supported JWT issuer configuration is documented; no hosted issuer was provisioned or tested.
- Full corpus semantic/lexical retrieval, transcript segmentation including late turns, source-ledger integration and reliable no-match behavior.
- Automatic upload/import indexing jobs and UI progress/retries; live-provider multimodal/token acceptance and truthful source state. Durable file reindex/deletion and reference-safe shared-attachment GC are implemented.
- Remaining UI API errors/cancellation/invalidation and component scenarios; handoff/retrieval inspector screens; review activity is implemented.
- Full backup/restore, forgetting tombstones/import ledger, labeled isolated demo fixtures/evaluation, reproducible CI/deployment/docs and real multi-client acceptance/recovery checks.

Every agent change requires parent full-diff review and relevant local tests before acceptance. See implementation-review-log.md for findings and verification limits.
