# Source provenance core

`lock_sources(session)` must be called before authoritative reads, in a fresh session transaction. It takes a transaction-scoped database lock. Call it again after every commit or rollback.

`record_write(session, *, kind, source_id, operation, actor=None, payload=None, source_revision=None)` appends a receipt and advances the head in the caller's locked transaction; it flushes but never commits. `kind` is `memory` or `profile`; `operation` is `created`, `updated`, `deleted`, or `reset`. An actor must be an admin. Creator identity is fixed at first observation, including across deletion and recreation. Legacy and previously unobserved updates have unknown creators. Payloads are represented only by SHA-256 of UTF-8 JSON with sorted keys, compact separators, and non-ASCII characters preserved; `None` has no hash.

`read_provenance(engine, kind, source_id, limit=20, offset=0)` returns `None` or a dictionary with `head` and descending `receipts`. Limits are 1–100. Receipts are bounded by the returned head revision, even if another transaction commits during the read. Pagination across separate calls can observe a newer head.

This foundation does not wire source CRUD or HTTP endpoints. Callers must lock before reading and write the source and receipt in the same transaction.
