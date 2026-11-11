# Coordination records

Handoffs are immutable agent reports, not approved facts. Their reported verified outcomes are claims by the writer. They never become accepted knowledge automatically. Save a handoff with an idempotency key, task name, summary, status, project and bounded lists of outcomes, unresolved items and next actions. The authenticated identity is the writer. Reusing a key with different content returns 409. Readers can retrieve the latest report or a paginated list in an authorized project. Global records require an administrator.

Memory issues identify an accepted knowledge record in the same scope and record a reason. Reporting an issue does not modify that knowledge. Readers see their own reports; administrators can list reports and resolve or dismiss an open issue with its expected revision. Both writes create activity events in the same transaction. Context includes the latest report only if it fits after accepted knowledge within the JSON byte budget.
