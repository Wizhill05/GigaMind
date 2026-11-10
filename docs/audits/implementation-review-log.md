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
