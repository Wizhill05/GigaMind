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
