# Conversation indexing

Conversation imports persist the source transcript independently of embeddings. Indexing is a durable background job: enqueue a conversation or a bounded backfill page, then run the job worker. Provider errors leave the source available and the job retrying or failed; they do not produce a partial index. Backfill skips already indexed or active conversations and returns a cursor for the next page.

The worker serializes the title, summary, and all message fields in order and splits the UTF-8 text into bounded segments. A segment boundary can fall inside a message; it is a byte-limit boundary, not a semantic boundary. It validates every vector before publishing the entire set in one transaction. Index metadata identifies the embedding model, dimension, source fingerprint, and segment count. Legacy conversation vectors alone are not evidence of a complete index. A source change requires a new job.

The import ledger lock serializes enqueue and publication with forgetting. A publication also checks its job ownership and active lease. Forgetting removes the source and derived segments and cancels its conversation jobs in the same transaction; a late provider response cannot restore them. Conversation jobs and file jobs use separate ownership states, even if their resource IDs are identical. Indexing does not create facts or assign project scope.


## API and operations

Administrator-only `POST /api/v1/conversations/{id}/vectorize` returns HTTP 202 with `success`, `id`, `job_id`, `state`, and `message`. An optional `idempotency_key` replays the original admission; it does not admit a new retry. Use a new key to explicitly retry. A forgotten source returns 404 even with an old idempotency key.

`POST /api/v1/conversations/backfill_vectors` accepts `cursor` and `limit` from 1 to 100, default 20. It returns HTTP 202 with `queued`, `skipped`, and `next_cursor`. The console queues one page per explicit action. This replaces the old process-local background task and synchronous single-conversation provider call. Admission does not mean indexing has finished. Imports themselves remain synchronous, transactional source ingestion; indexing is requested separately.

Run `python -m gigamind.cli.worker` with the same database and embedding configuration as the web process. Jobs, conversation lists and the transcript drawer show state and job IDs. The Jobs console can cancel active work or admit a new retry with `index_conversation` and payload `{"conversation_id": "..."}`. Changing model or dimension makes the previous index ineligible until rebuilt.

Text search keeps the complete provider-free lexical path and also compares queries with current transcript segment vectors. Filters apply before reading candidates. It ignores old preview vectors without model and coverage metadata. Evidence from semantic-only matches is labeled `indexed_segment`, with model/dimension and a bounded literal excerpt. Segments can split a message and are not independently accepted knowledge. The current retrieval path scans filtered sources and their stored JSON vectors; it has no native approximate-nearest-neighbor segment index. Raw cosine scores are not calibrated relevance confidence. Offline deterministic vectors prove publication and retrieval behavior, not provider quality or tokenization on real transcripts.
