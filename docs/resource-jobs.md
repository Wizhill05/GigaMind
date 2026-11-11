# Resource job ownership

Each file key has a durable owner and tombstone. Enqueue serializes on that row, cancels active older jobs and assigns the new owner in one transaction. Repeating an idempotency key returns its original job without changing ownership. Publication locks and checks the owner before checking the job lease in the indexing transaction.

`cancel_resource` cancels active jobs only. Call `forget_resource` before deleting file or index data; it tombstones the key and cancels active jobs atomically. Normal enqueues cannot recreate a tombstoned key. Uploads should use fresh unique keys; restoration policy is separate.

Jobs created before ownership tracking have no owner and fail closed at publication. Enqueue a new job to index such a resource. HTTP upload, reindex and delete integration is separate.
