# Accepted record deletion

An administrator can call `POST /api/v1/review/memories/{id}/delete` with a JSON body containing the current integer `expected_revision`. Only an accepted record can be deleted. A stale revision or a record that is no longer accepted returns 409. The transaction records a deleted revision and actor activity without changing the content.

Administrators retain access to review details and history. Other readers cannot retrieve a deleted record or its history; MCP exact retrieval excludes it for every actor. Search and context exclude deleted records. An administrator may restore a prior revision using the restore endpoint and the current revision; accepted-subject conflict checks still apply.

This tombstone retains content for audit and is not physical erasure. Expiry and handoffs are outside this operation.
