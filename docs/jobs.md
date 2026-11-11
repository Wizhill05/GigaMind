# Jobs

Run a separate worker process with `python -m gigamind.cli.worker`. Use `--once` to process at most one available job, `--poll-seconds` to set the idle polling interval, and `--lease-seconds` to set the renewable lease duration. SIGINT and SIGTERM stop the worker after its current handler finishes; its lease continues to be renewed while it runs.

The admin-only `/api/v1/jobs` API accepts `index_file` jobs with a payload containing only `key`. Optional idempotency keys make identical submissions return the existing job; reuse with different parameters is a conflict. Jobs report queued, running, retrying, completed, failed or cancelled state. Storage and embedding services must be configured for file indexing to succeed.

Existing upload, import, reindex and deletion routes do not automatically use this queue. The queue does not yet establish latest-resource ownership or current-resource tombstones; do not rely on it to coordinate those routes.
