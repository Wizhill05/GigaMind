# Upload preparation core

`prepare_upload(key, filename, mime_type, multimodal_type, size_bytes, source_agent, idempotency_key, *, engine=None, clock=jobs.utcnow)` accepts already validated metadata and returns `(file_dict, job_dict)` after one database commit. The caller supplies a stable, immutable, uniquely allocated key and an authenticated source identity; the service performs no remote IO. A repeat requires the same key, metadata and idempotency key. Existing keys cannot be replaced. Tombstones raise HTTP 409; conflicts raise `jobs.Conflict` for the route to map to HTTP 409.

The job is deferred until `acknowledge_upload(key, job_id, *, engine=None, clock=jobs.utcnow)` verifies it remains the current queued owner and makes it eligible. Call this only after confirming remote upload success. The route must ensure the object is created without overwriting existing remote content and enforce authorization. No route integration or distributed transaction exists yet. A crash after preparation leaves a pending job; recovery must verify the remote object and acknowledge it, or retry an idempotent upload using the same immutable key. A crash after remote upload but before acknowledgement requires the same verification. Do not acknowledge when storage is disabled or upload failed. Abandoned preparations require operational cleanup coordinated with the file lifecycle.

Acknowledgement is idempotent for the same current prepared file/job after eligibility, during indexing and after its terminal result. It returns the existing state and does not reset retries or a live lease. Cancelled, superseded and forgotten preparations cannot be revived. Internal not-before values must be timezone-aware datetimes.
# Upload manifests

Pass `sha256` as a lowercase SHA256 hex digest to `prepare_upload` to persist
the expected digest and size with the file and deferred job. `begin_upload(key,
job_id, *, engine=None, clock=...)` grants one caller the right to issue one PUT.
Never repeat that PUT for the key. After an uncertain outcome call
`record_unknown(key, job_id, *, engine=None, clock=...)`. Fetch the actual remote
bytes and call `verify_upload(key, job_id, remote_bytes, *, engine=None,
clock=...)`; pass `None` when absent. ETags are not checksums. Only matching
bytes permit acknowledgement, and acknowledgement still requires a current,
non-cancelled owner. Verification can finish after cancellation.

An absent or mismatched object remains unresolved. Deletion is blocked for
in-flight and unknown outcomes even after cancellation, because a late PUT may
still complete. There is no force-abandon operation or distributed transaction.
Prepared uploads can be deleted before admission. Route integration and remote
fetching are the caller's responsibility.
