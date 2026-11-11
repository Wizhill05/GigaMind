Implementation review log

2026-11-10, parent review of 941bf59 (full diff, both files)

Accepted as an intermediate foundation only: missing annotation import fixed; memory deletion/reset now commit; unrelated/shared storage no longer synchronously destroyed; category/source predicates applied before memory/profile ranking; listing counts logical parents.

Not release-ready. Required follow-up:
- Implement actual project storage and scope enforcement; get_memories currently raises for project IDs.
- Add evidence-backed proposals, revisions, restore, conflicts, handoffs, issues and activity router/services.
- Rebuild chunks on edits, not merely delete them; keep vectors/source revision consistent.
- Implement SQLite semantic candidates and corpus lexical indexing, not unbounded Python scans.
- Add migrations and embedding metadata; replace table-loading stats with aggregates.
- Add durable attachment cleanup after safe unlink; retained bytes are not a complete lifecycle.
- Commit meaningful isolated behavior tests. Existing-suite 4-pass/14-fail is not acceptance.

Integration does not imply completion of the audited roadmap. Original isolated audit and implementation contract remain authoritative scope.

2026-11-10, parent full-diff review of 5f9094d and e6e7aea

Integrated as intermediate foundations only. Parent TestClient checks independently passed: missing/forged REST credentials rejected, unauthenticated MCP rejected, incomplete OAuth returns unavailable, scoped credential creation, denial of legacy admin routes, revocation enforced, admin stats still available. Parent production frontend build passed.

Security blockers: MCP and OAuth deliberately unavailable, no supported SDK transport, no grant lifecycle, no readiness/schema validation, limited input/upload bounds, no persistent tests. Credential lifecycle lacks expiry/timestamps/last use and service-level validation. Root metadata still advertises unavailable features.

Frontend blockers: Escape listeners retain a pre-save closure and can close pending-save dialogs; save errors are not reset on new modal opening. Backend does not read the new q parameter. Delete refresh ignores active search. Category/source pagination reset incomplete. Most API functions still suppress errors. Review console and behavior tests absent. Active-tab remount refresh is an intermediate approach, not shared query invalidation.

Trust correction 5665f851 returned no changes. Its dependency concern is now resolved by integrating security.py. The next trust task is narrowed to proposal/approval/revision core with independent SQLite tests; no further partial scaffold is accepted as completion.

2026-11-10, parent full-diff review of 12c368e

Four tables, service module, router and both tests read in full. Staged on the integration branch for corrective work, NOT accepted as a finished trust unit. Required corrections:
- Different proposals for one subject can race to approval; enforce one active subject fact with database structure and concurrency tests, including restore and NULL/global scope.
- Restore conflict detection must exclude the record being restored.
- Prevent identical same-subject accepted duplicates; define retry and reuse behavior.
- Validate evidence and normalized project/subject/content at the service boundary, not just HTTP models. Current str(None) check can accept missing evidence text through direct service calls.
- Lists load all rows then filter in Python; enforce project predicates in SQL and add stable bounded pagination.
- Two test functions cover happy-path and limited isolation only. Add actual conflicting/concurrent approvals, restore and fresh-session persistence, idempotent races, denied global/activity access and structured router validation.
- Router must be mounted and tables migrated during application integration, and approved knowledge must participate in scoped retrieval in a later unit.

2026-11-10, parent full-diff review of 0988a68 and a43e11e

Read all changed application sources, tests and dependency changes. Accepted working admin MCP transport as a bounded foundation: actual SDK initialize/list/call passed in parent run with mcp==1.26.0, REST q forwarded, readiness and list bounds work. Scoped trust tools/OAuth remain missing and scheduled later. Parent fixed test's broad ExceptionGroup catch that could mask AssertionError, replacing it with an explicit post-revocation 401 assertion. Parent reran MCP+trust tests: 3 passed.

Accepted frontend save/search fixes as intermediate progress. Parent fixed Escape regression test: immediate assertion could pass before the 180ms close timer, so advance fake timers past close before assertion. Parent reran tests: 6 passed. Build passed. Remaining frontend work: all helper/caller error propagation, cross-tab invalidation, indexing polling, focus trap, authentication/list scenarios and new review console. Six focused tests do not establish whole-UI correctness.

2026-11-10, parent full review of bdab590 and uncommitted statistics patch

Read all changes including shared schemas. Parent verified shared /tmp/gigamind-audit-venv/bin/python imports sqlmodel successfully; lack of sqlmodel in another interpreter did not block meaningful tests.

Trust correction accepted after parent changes: explicit IF NOT EXISTS index DDL upgrades existing tables without relying on SQLite expression-index reflection; validated normalized resolution/restoration inputs are actually used; non-concurrency OperationalError is no longer mislabeled 409; sources reformatted for readability. Added real restore-versus-approval races for both project and global scope, idempotent-create race with one event, old-index upgrade checks, normalized inputs and global/activity visibility tests. Parent trust+MCP run: 11 passed. These are SQLite behavior tests plus PostgreSQL DDL compilation, not live PostgreSQL integration.

Reviewed small uncommitted stats patch from de6805ae and integrated only SQL aggregates/logical-parent counts and bounded service pagination. Added a persistent logical-memory count/list regression test; parent test passed. Source-first indexing/migrations/retrieval remain outstanding, now split into separate units. Trust router/context integration and remaining product work remain outstanding.

2026-11-11, resume after provider usage limits

The latest frontend focus/export/reset diff (2b0ccd4) was reviewed in full on 2026-11-10. Parent reran 8 frontend tests and production build successfully. Router integration is now committed: review API mounted, trust tables/index initialized and exact accepted-memory endpoint added. Parent full-app HTTP probe verified scoped proposal creation, denied agent approval, admin approval, memory retrieval and revision history. Generated frontend build changes restored; source remains authoritative.

Migration and source-index workers failed from provider quota while holding unfinished drafts. Preserve those worktrees and resume the actual changes in fresh isolated tasks; no draft is accepted as complete. All original roadmap requirements and review/fix obligations remain in scope.

2026-11-11, parent full-diff review of migration unit 2e5e622

Read database.py changes, all migration code and all tests. Parent reran 18 existing SQLite/trust/MCP/count checks successfully, then started an isolated loopback PostgreSQL 16 + pgvector Docker test service, image digest sha256:0dd3149a06e4579a0d70d8fef9945636cd514005e7237deb27f9b67886f8dc4f. No hosted database touched.

Parent corrections: wire schema readiness into /health/ready; readiness now checks native vector dimensions/types and valid HNSW indexes. Normalize standard PostgreSQL URLs to installed psycopg2 driver (SQLAlchemy's new default otherwise imports missing psycopg). Scope migration inspection/DDL to the connection's current schema, preserving isolation when public contains other tables. Register vector reflection type, validate attachment backfill shape, and reformat migration code.

Added persistent optional local PostgreSQL integration tests for fresh/native upgrades, vector writes, HNSW repair, dimension mismatch, dropped vector column, transactional DDL rollback, full production-mode app startup with standard connection URL, and simultaneous same-subject approvals leaving exactly one accepted fact. Added SQLite readiness and malformed-attachment rollback tests. Parent combined run: 24 passed before adding native approval race; final native suite: 5 passed. Unchanged SQLite/MCP portion has 20 passing checks. Local Docker service stopped and removed after testing. Migration unit accepted; source indexing model registration will be verified when its worker returns.

2026-11-11, parent full-diff review of c6ac57e and 9136a4b

Read the complete source/index-state changes, all indexing tests, all review UI/API/tests and navigation/dependency changes. Parent reran frontend tests (13 passed) and production build. Review UI is intermediate: edited text can invalidate listed conflict IDs with no recovery; busy selection changes and compressed state/render code need correction, and non-409 failure coverage is missing. Added backend read-only /review/proposals/{id}/preview contract to recompute conflicts for exact edited content/revision without resolving anything; unauthorized and stale previews rejected. UI follow-up must use it rather than auto-supersede.

Indexing core accepted after parent corrections: restored transactionally registered attachment metadata (source rewrite had removed it), preserve completed state after failed duplicate retries, reject blank source, report deletion during initial indexing as409 rather than fake saved ID, make legacy state initialization an upsert, forward expected_revision through REST and React edit calls, fix the count-test embedding stub's dimension locally, and format only changed memory functions for readability. Added regression tests for attachment retention, failed duplicate retries, legacy state creation, stale REST updates and deletion during initial indexing.

Parent backend combined run before final two small regressions: 37 passed, including six native PostgreSQL/pgvector tests. Final indexing-only run: 12 passed; final native suite: 6 passed. Native indexing verifies full chunk vector dimensions, one provider call per chunk, long-to-short replacement, revision rejection and source preservation with cleared native vectors after provider failure. No hosted data touched. Local test Docker service removed afterward. Remaining product scope still tracked in implementation-status.md.

2026-11-11, parent full-diff review of scoped retrieval 662ed88

Read context service, protocol/router changes and all SDK/context tests. Parent corrected authority semantics: accepted-knowledge tools no longer silently fall back to unreviewed legacy memories when nothing matches. Added approved preference rules to context even for unrelated tasks, while retaining project filtering and conservative serialized-byte budgets. Added lexical term relevance ordering and removal of question stopwords so trivial query words do not create arbitrary matches. Admin omitted-project context/search defaults to global knowledge rather than mixing project-specific rules; unauthorized projects are checked even for empty lexical queries. Scoped exact retrieval still labels historical statuses explicitly.

Parent updated real SDK fixture to approve its fixture knowledge and added scoped preference/global-default regressions. Focused context/MCP/trust run: 15 passed before the final global-default regression. Retrieval remains lexical, not semantic or multimodal; handoff remains null pending that unit. This is an accepted scoped retrieval foundation, not the complete retrieval roadmap.

2026-11-11, OAuth worker ee24bbfe review

Read its completion transcript and checked its checkout: no changes or commit. Nothing accepted. OAuth remains unavailable; split replacement into signed-token verifier first, then persistent local bindings/discovery/lifecycle integration. Existing unused in-memory issuer must not be restored to mounted routes.

2026-11-11, parent review of jobs draft bfcf8301 and verifier f06670fb

Jobs: read every draft file and main registration diff. Draft is NOT accepted: only two sequential tests; missing real concurrent claims/idempotency, heartbeat and HTTP authorization coverage. More seriously, cancellation only protects job-row completion, not the indexing handler's side effects. Add lease fencing inside the file-index publication transaction and cancel file jobs before index deletion. Existing index service separately commits native vectors and suppresses their errors, so worker success can be false; correct that within this integration. Preserve draft in worktree 514493ab for focused corrective worker.

Verifier: read all code, signer/local-server tests and dependency change. Parent original tests: 19 passed. Parent tightened issuer URL validation (was only JWKS URL) and rejects loopback HTTP in production even when explicitly enabled. Added invalid-issuer and production-loopback regressions; parent final verifier run: 25 passed. JWT identity verification accepted as foundation only; binding, scopes, discovery and credential lifecycle still require integration. No real issuer or keys accessed.

2026-11-11, parent full-diff review of review-screen correction f8bccce

Read all three changed source/test files. Accepted the edited-content conflict preview, abort guards, explicit supersession, draft-preserving retries, local list refresh and restore refresh. Parent fixed a server/client normalization mismatch that prevented approving whitespace-padded drafts, added a regression, debounced previews and made preview loading visible even when there are no conflicts. Disabled retry controls during mutations and strengthened the delayed-preview test to wait until the old request actually starts before changing drafts. Parent frontend verification: 18 tests passed; production build passed with dependency annotation warnings. Generated dist restored. Broader frontend error handling and approved/legacy memory presentation remain tracked separately.

2026-11-11, parent full-diff review of OAuth binding/discovery f70b140

Read all eight changed files, including verifier configuration, per-request actor mapping, MCP challenge forwarding and binding APIs. Parent added actual SDK integration with generated RSA keys and a local JWKS server, proving project A retrieval/context, global and project B denial, scope intersection, admin denial and immediate binding revocation. Tests exercise the real verifier and transport without real issuer credentials. Parent isolated the binding HTTP test database, added HTTP admin/pagination checks, bounded binding lists and bearer lengths, fixed non-ASCII bearer strings causing hmac TypeError, tightened canonical resource-origin validation and formatted the new authentication code.

Parent verifier/resource/MCP run: 31 passed. External JWT resource authorization accepted with documented operator configuration. This does not provision an authorization server or prove interoperability with a particular hosted provider. Credential expiry/last-use and operator UI remain outstanding.

2026-11-11, review of incomplete queue correction a02869bb

Read the draft job service/model/router, indexing publication diff and existing tests in its isolated worktree. Changes are still uncommitted and not integrated. Lease checks and native-vector writes now share a publication transaction in the draft, but the only two tests do not exercise them. Resource cancellation, mounted routes, bounded service inputs, concurrent claims and actual heartbeat/publication coverage remain missing. No queue functionality accepted. Split the queue core and file-publication verification into smaller independent units; preserve draft at t3-e3447d30.

2026-11-11, parent full-diff review of file publication e911b82

Read indexing changes and every new test. Parent SQLite run: 5 passed. Parent added native PostgreSQL/pgvector integration exercising real text parsing/chunking, multi-chunk publication, a PostgreSQL trigger that fails chunk-vector publication after parent-vector/metadata updates begin, rollback of both index writes and a guard-side counter, successful long-to-short replacement and empty replacement clearing native vectors. Combined publication/native suite: 12 passed, including seven native checks. Local Docker service stopped and removed after testing; no hosted database touched.

Parent tightened vector input types to reject booleans, numeric strings and mappings, narrowed the SQLite rollback assertion to the actual SQL error, added per-case preservation assertions and formatted touched functions/tests. Final focused SQLite run: 5 passed. Publication hook/atomic write unit accepted. This does not complete job integration: actual JobLease cancellation/late-publication tests, latest-resource-job ownership and upload/delete/HTTP integration remain required after queue core returns.

2026-11-11, parent full-diff review of queue core 4c73446 and demo a82b0f1

Read all queue model/service/tests/docs and all demo CLI/fixtures/tests/docs. Original queue/demo run: 14 passed. Parent fixed claim snapshot timing: read the token/state while still holding the claim transaction and retain it across commit, so cancellation/reclaim after commit cannot substitute another owner's token. Added a deterministic after-commit cancellation regression, rejected unsupportably short leases, bounded resource keys by UTF-8 bytes for indexed storage and formatted core code.

Parent added actual job-handler/indexing integration tests: successful persisted file index, paused embedding cancelled then deleted without resurrection, and reclaimed lease preventing both stale publication and stale completion while allowing the replacement owner to finish. Final queue/core/publication/demo run: 21 passed. Added native PostgreSQL concurrent idempotent enqueue, concurrent claim and revoked-lease publication/completion tests; native suite: 8 passed. Local test container stopped and removed. Queue core accepted; HTTP/CLI, startup registration, latest resource ownership, uploads and delete-route integration still required.

Demo accepted after parent added varied topic-specific source notes, strict production-environment normalization and tests for existing/symlink/remote targets, unchanged database bytes, project/global denial, pending-proposal exclusion and lexical fixtures. Final demo tests: 2 passed. It contains 64 explicitly synthetic source memories, 15 conversations and reviewed facts/rules/proposals/history. No provider calls, fake vectors, real user data or hosted database writes. The CLI has not been run against any non-test database and no demo server has been started.
