# File cleanup

Both file deletion endpoints require an admin and return HTTP 202 with `key`, `job_id`, `state`, and `cleanup` (`pending` or `completed`). Acceptance records durable intent, not physical deletion. The admin jobs endpoint reports progress. Repeated requests return the active or completed job; a failed cleanup can be requested again. References block deletion with HTTP 409.

The worker retries unacknowledged deletion, including when storage is disabled, and reports completion only after storage acknowledges it. Cleanup is at least once, so storage deletion must be idempotent for missing objects. The tombstone prevents new application attachments and hides the file from listing, chunks, new download URLs and reindexing. Existing presigned URLs remain usable until they expire. Direct presigned uploads are disabled until an upload completion protocol exists; other upload paths still need lifecycle integration.

The worker checks ownership, its lease and references in a transaction, then releases database locks before calling storage. Cancellation or lease expiry cannot retract an admitted storage request; a replacement worker may repeat the delete. Completion requires the current lease. Cancellation does not restore a tombstoned resource.
