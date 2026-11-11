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
- Auth/list race, deletion, credential and activity behavior verified in the frontend suite; production build passes. Client expiry, throttled last use, atomic rotation/revocation and v2 legacy migration are verified, including native races.
- Full decoded transcript lexical search without a provider, optional existing vector candidates with SQL prefilters, source snippets and native search checks.
- MIME-safe text/image embedding requests, all-page PDF anchors, stored-metadata reindex and strict provider-vector validation. Offline payload and native publication checks pass; live-provider OCR/token/relevance acceptance remains unfinished.

Additional reviewed features:
- Admin upload/recovery routes now use durable registration, one immutable PUT, bounded remote verification and checksum-gated acknowledgement. Authenticated HTTP tests cover collisions without overwrite, decoded 20 MB limits, cancelled in-flight uploads, stale/missing/mismatched recovery and tombstones. A real unrelated indexing worker renews its lease during a blocked upload. These are local tests with provider/storage boundaries substituted.
- Jobs console supports progress, cancellation, indexing/cleanup retries, polling, hidden-tab pause and stale-response protection. Approved Knowledge console supports project/status filters, evidence, history, revision-checked deletion/restore and explicit conflict reload. Both are tested through the real App authentication and header-refresh flows.
- Global-body limits and local CI verification are implemented. Reference-safe cleanup, delete/reindex routes, tombstone access fencing, credential lifecycle and review activity are reviewed and integrated.

In review:
- Scoped immutable handoffs and memory issues, REST/MCP tools and context integration are reviewed and accepted. Scope/revocation, zero-scope SDK denial, rollback and native idempotency/migration checks pass; coordination UI remains unfinished.
- Conversation list error/retry, cancellation and header refresh are implemented provisionally, with parent source-role/provenance corrections. Search/list behavior is now reviewed and accepted with79 frontend tests and a successful production build, including stale response, credential-change retry, evidence, filtered deletion and last-page checks. Mutation error/import retry work is integrated, but shared App/tab/drawer locking and remaining mutation HTTP scenarios still require completion.
- Local SQLite backup/new-path restore is reviewed and accepted, including input digest/WAL checks, observed concurrent write, actual credential/upload services and trust-history recovery. Parent59 focused checks pass. PostgreSQL and object recovery remain unfinished.

Still required:
- Approved records are available through scoped context/MCP tools and a dedicated Knowledge console. They remain separate from legacy MemoryItem storage; richer retrieval and clear source presentation remain required.
- Handoff/issue console, temporal validity/expiry and complete authenticated provenance through legacy admin CRUD. Approved-record deletion, read redaction and admin audit/restore are implemented with stale-supersession protection.
- External-provider interoperability acceptance. Decoded-file upload bounds and global encoded-body limits including MCP are implemented. Credential expiry/last-use/rotation and credential console are implemented. Supported JWT issuer configuration is documented; no hosted issuer was provisioned or tested.
- Full corpus semantic/lexical retrieval, transcript segmentation including late turns, source-ledger integration and reliable no-match behavior.
- Automatic import indexing jobs, live-provider multimodal/token acceptance and complete source state presentation. Upload indexing, file reindex/deletion, Jobs progress/retries and reference-safe shared-attachment GC are implemented.
- Remaining UI API errors/cancellation/invalidation and component scenarios; handoff/retrieval inspector screens; review activity is implemented.
- Full backup/restore, forgetting tombstones/import ledger, labeled isolated demo fixtures/evaluation, deployment/docs and real multi-client acceptance/recovery checks. Offline CI is implemented and locally verified:277 backend tests pass with24 optional native checks skipped; all24 native checks passed separately. The frontend suite has65 passing tests and a successful production build. The final Knowledge conflict guard additionally passes all8 focused Knowledge tests and a fresh build. Hosted CI has not been run.

Every agent change requires parent full-diff review and relevant local tests before acceptance. See implementation-review-log.md for findings and verification limits.
