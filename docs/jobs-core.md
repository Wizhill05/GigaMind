# Durable job core

The queue persists index-file requests and uses unique idempotency keys. Reusing a key with different parameters conflicts. Workers claim jobs with expiring tokens, renew leases while handlers run, and retry transient failures up to the configured attempt limit. Public failure messages omit exception details.

Execution is at least once: a worker can perform work and crash before recording completion, so handlers must tolerate retries. Before publishing results, the indexing transaction must call `JobLease.publication_guard(session)` in the same transaction as its writes. The guard takes a database write/row lock and rejects expired, cancelled, or replaced leases. Deletion integration must call `cancel_resource` for the exact key and coordinate deletion with publication transactions.

This core does not mount HTTP routes or automatically enqueue uploads. Those and the indexing publication-guard integration are separate work. Existing databases need a migration for the jobs table and resource index before use.
