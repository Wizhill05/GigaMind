# Jobs

Run a separate worker process with `python -m gigamind.cli.worker`. Use `--once` to process at most one available job, `--poll-seconds` to set the idle polling interval, and `--lease-seconds` to set the renewable lease duration. SIGINT and SIGTERM stop the worker after its current handler finishes; its lease continues to be renewed while it runs.

The admin-only `/api/v1/jobs` API accepts `index_file` jobs with a payload containing only `key`. Optional idempotency keys make identical submissions return the existing job; reuse with different parameters is a conflict. Jobs report queued, running, retrying, completed, failed or cancelled state. Storage and embedding services must be configured for file indexing to succeed.

For production, run the worker as a separate continuously running process from the same release and locked Python environment as the web service. Configure the same `DATABASE_URL`, R2 settings, and embedding/provider settings on both processes. Use a shared PostgreSQL database and shared object storage; separate local SQLite files or ephemeral disks do not form a shared queue. The web process alone does not execute jobs.

On Render, create a separate Python background worker using the same repository and release, `pip install -r requirements.txt` as its build command and `python -m gigamind.cli.worker` as its start command. Set Python 3.12.16 and copy the same database, storage, and provider configuration securely to it. The Blueprint currently defines only the web service; creating a worker incurs a separate paid compute charge. See [Render background workers](https://render.com/docs/background-workers) and [compute plans](https://render.com/docs/compute-plans). Do not deploy until the shared configuration is in place.

`Worker ready` means database initialization completed and the polling loop is about to start. It does not prove storage or provider connectivity, successful job execution, or continuous health. Monitor process exits and job failures/backlog separately. Shutdown waits for the current handler, subject to the hosting platform's shutdown timeout.
