# Conversation imports

Import ChatGPT or Claude JSON with `python -m gigamind.cli.importer --chatgpt export.json` or `--claude export.json`. The REST service uses the same adapter. A batch is validated before writing. ChatGPT imports follow the selected current node; exports without one must have a single unambiguous branch. Identical source versions deduplicate; changes produce a new source version.

Imports preserve transcript text as sources and do not create facts. Embeddings are empty and indexing is pending. Transcript segmentation, semantic indexing, forgetting tombstones and a durable import job ledger are future work. Imports are limited to 20 MB and 5,000 conversations per batch.

Numeric source creation times are converted to UTC ISO dates. If the source omits its creation time, the stored record uses its receipt time; this does not change the version identity on repeated imports. `pending_indexing` counts newly stored sources awaiting indexing. Concurrent identical imports insert one source version. Older records with legacy truncated IDs are retained; their first canonical re-import can create a new version. Full import-ledger provenance and forgetting tombstones remain unfinished.
