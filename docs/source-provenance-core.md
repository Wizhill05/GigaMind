# Source provenance

Memory and profile CRUD now records credential attribution in the same database transaction as each authoritative source change. REST routes supply the authenticated administrator actor. The caller's `source_agent` is retained as a claim in the source record and never supplies the credential ID. Direct service calls without an actor are explicitly unattributed. Existing sources migrate with unknown original attribution; their first later editor does not become their creator.

The Memory, Profile and Files lists have a History action showing the original credential, active/deleted source state, and paginated change receipts. Credential attribution identifies a submitting account. Source authorship and factual accuracy require separate verification. Source memories and administrative profile rules remain separate from reviewed Knowledge used for scoped agent context.

## API

`GET /api/v1/sources/{kind}/{id}/provenance` is administrator-only, including reads of deleted-source metadata. `kind` is `memory`, `profile`, or `file`. File IDs identify registered metadata, not object keys. `limit` defaults to 20 and accepts 1–100; `offset` defaults to 0 and accepts 0–1,000,000. URL-encode the opaque source ID; legacy IDs containing slashes and other reserved characters remain supported. An unknown source returns 404. Directly seeded sources without receipts return explicit legacy-unknown attribution without creating audit data on a read.

The JSON response has `head`, descending `receipts`, `total`, `limit`, and `offset`. The head contains `kind`, `source_id`, `revision`, `active`, `creator_id`, and `creator_provenance`. Creator provenance is `authenticated`, `unattributed`, or `legacy_unknown`. Each receipt contains its kind/source ID, positive receipt revision, operation, writer ID and provenance, optional payload hash and actual source revision, and a UTC timestamp. Receipt writer provenance is `authenticated` or `unattributed`.

The receipt counter is distinct from the memory index/source revision. Memory receipts include that actual source revision as a decimal string when available. Profile receipts have no separate index revision. A page is bounded by the returned head revision, including when a writer commits between the head and receipt reads. Separate page requests may observe a newer head.

## Transactions

`lock_sources(session)` must run before authoritative reads in a fresh session transaction. SQLite uses `BEGIN IMMEDIATE`; PostgreSQL uses transaction advisory lock `723649823`. Lock again after commit or rollback. Source CRUD holds this lock only during database changes; embedding calls run after the source and its receipt commit. Index failure preserves both the source and its attribution.

`record_write(session, *, kind, source_id, operation, actor=None, payload=None, source_revision=None)` appends a receipt and advances its head in the caller's locked transaction. It flushes and never commits. Operations are `created`, `updated`, `deleted`, and `reset`; files also support `verified`. File registration, checksum verification and forgetting have distinct meanings. See [file source provenance](file-source-provenance.md). Supplied actors must be administrators. The optional actual source revision must be a nonnegative integer and is stored as a decimal string. Reusing a session after its transaction ends requires a new lock.

`read_provenance(engine, kind, source_id, limit=20, offset=0)` returns `None` or the page described above. Its reads do not change domain records.

Profile writes serialize key lookup and mutation. Existing row IDs remain stable; new memory and profile rows use complete UUIDs. Deleting and recreating a profile key creates a new source ID. Source heads retain their original creator across any reuse of the same logical ID. Memory deletion/reset fences the index-state row before deleting the current source and derived chunks, so a publisher finishing during deletion cannot leave new orphan chunks. Individual derived chunks cannot be deleted through logical memory CRUD.

## Retention and limits

Receipts retain identifiers and SHA-256 hashes of canonical source payloads, with no copied source text, profile values, attachments, or embedding vectors. Canonical hashes use sorted-key compact UTF-8 JSON. Memory payload fields are ID, content, category, media type/URL, claimed source agent, stored tag and attachment JSON, and source creation time. Profile payload fields are ID, key/value, category, claimed source agent, and update time. Derived indexing state and access timestamps are excluded. Delete/reset receipts have no payload hash.

Deleting source data retains its credential receipts. Existing backups and other copies have separate retention. Legacy unknown creators stay unknown. Receipts cover this release's shared services; direct SQL changes and older application writers can bypass them. Use the same release across writers. These receipts are an application audit, not protection against a database administrator rewriting history. They do not add project scope to legacy storage or promote sources into accepted facts.
