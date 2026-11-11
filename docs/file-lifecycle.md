# File cleanup core

`request_delete(actor, key, engine=None)` requires an admin Actor and returns a durable Job. It rejects referenced keys with HTTP 409, tombstones unreferenced keys, removes their index metadata, and queues object cleanup in one transaction. A repeated request returns the current active or completed cleanup; a failed cleanup can be retried by requesting deletion again.

A future route may return HTTP 202 with the job reference: this records intent, not completion. The worker retries unacknowledged deletion and reports completion only after storage acknowledges it. Cleanup is at least once, so storage deletion must be idempotent for missing objects. No route is wired by this unit.
