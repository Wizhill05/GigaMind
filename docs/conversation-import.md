# Conversation imports

Import ChatGPT or Claude JSON with `python -m gigamind.cli.importer --chatgpt export.json` or `--claude export.json`. The REST service uses the same adapter. A batch is validated before writing. ChatGPT imports follow the selected current node; exports without one must have a single unambiguous branch. Identical source versions deduplicate; changes produce a new source version.

Imports preserve transcript text as sources and do not create facts. Embeddings are empty and indexing is pending. Transcript segmentation, semantic indexing, forgetting tombstones and a durable import job ledger are future work. Imports are limited to 20 MB and 5,000 conversations per batch.
