# File cleanup core

`request_delete(actor, key, engine=None)` requires an admin Actor and returns a durable Job. It rejects referenced keys with HTTP 409, tombstones unreferenced keys, removes their index metadata, and queues object cleanup in one transaction. A repeated request returns the current active or completed cleanup; a failed cleanup can be retried by requesting deletion again.

A future route may return HTTP 202 with the job reference: this records intent, not completion. The worker retries unacknowledged deletion and reports completion only after storage acknowledges it. Cleanup is at least once, so storage deletion must be idempotent for missing objects. No route is wired by this unit.

The worker checks ownership, its lease and references in a transaction, then releases database locks before calling storage. The tombstone prevents new application attachments during that call and permits heartbeat renewal. Cancellation or lease expiry cannot retract a storage request already admitted; a replacement worker may repeat the idempotent delete. Job completion still requires the current lease. Cancellation does not restore a tombstoned resource.
