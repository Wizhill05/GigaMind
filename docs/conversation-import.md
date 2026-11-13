# Conversation imports and forgetting

Import ChatGPT or Claude JSON with `python -m gigamind.cli.importer --chatgpt export.json` or `--claude export.json`. The authenticated REST upload uses the same normalizer. A batch is validated before any database write. Imports are limited to 20 MB and 5,000 conversations per batch.

ChatGPT imports follow the selected current node. Exports without one must have a single unambiguous branch. Messages retain complete text, recorded roles, message or branch-node identifiers, and available timestamps. Identical normalized source versions deduplicate; changed text or metadata produces a separate source version. Versions never overwrite an earlier transcript. Numeric source creation times become UTC ISO dates. Missing creation times use receipt time without changing the normalized version identity.

Imports store sources without promoting them to accepted facts or calling an embedding provider. Newly imported records have empty embeddings. `pending_indexing` counts those new records. Durable import jobs, transcript segmentation, and semantic indexing remain separate work.

## Import receipts

Schema version 6 adds `conversation_sources` and `conversation_receipts`. Each source has a hashed identity key. A nonblank upstream `id` or `uuid`, together with the normalized platform, identifies the source. Without one, the exact normalized version fingerprint identifies it. The receipt stores the canonical content digest, receipt time, authenticated importer ID when available, provenance, and later deletion metadata. The claimed `source_agent` remains export metadata and never supplies the authenticated writer ID.

REST receipts use `authenticated` provenance. CLI receipts use `local_cli` with no authenticated writer. Direct service calls without an actor are `unattributed`. Existing rows migrate as `legacy_unknown` with no invented writer, original receipt time, or upstream ID. Reimporting an exact canonical legacy version can establish its upstream identity and digest while preserving its unknown original attribution. Older truncated IDs cannot be matched reliably to canonical versions.

Exact conversation reads include a `provenance` object. Import responses preserve existing counts and add `duplicates`, `forgotten`, and per-record `records` with an ID, source key, digest, and `ingested`, `duplicate`, or `forgotten` status. `skipped` includes duplicates and forgotten sources. Repeated imports never clear a forgetting tombstone.

## Forgetting a source

Deleting any version of a known imported source atomically removes **all its stored transcript versions** and records a durable upstream-identity tombstone. Later imports with the same platform and upstream ID are blocked, including changed versions and imports after process restart. Repeated deletion is idempotent. Removed transcripts no longer appear in listing, text search, exact reads, or stored-source evidence inspection.

SQLite uses an immediate write transaction. PostgreSQL uses a transaction-level advisory lock shared by import and deletion. The lock serializes batches and forgetting across processes. Transcript rows, receipts, and tombstones commit or roll back together. It does not cover unrelated direct database writes.

A source without a stable upstream ID can block only its exact normalized fingerprint. Changed metadata or text produces a new fingerprint and can be imported. A legacy row with unknown upstream identity can block its exact canonical ID, but cannot block unidentified changed exports until a matching reimport establishes that identity. Changing or omitting an upstream ID or platform can also create a different source identity. This is not a content-based erasure guarantee.

The ledger retains minimal identifiers and hashes, not transcript snapshots. SQLite pages, backups, separately reviewed knowledge, proposal quotes, handoffs, and other copied content have separate retention. Source deletion does not erase those copies or clear existing review decisions. There is no import override that silently restores a forgotten source.
