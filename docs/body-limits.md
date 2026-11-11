# Request body limits

HTTP request bodies are limited before application handlers run, including MCP requests. The default is 1 MiB. The exact paths `/api/v1/files/upload` and `/api/v1/conversations/import_file` allow 21 MiB for multipart overhead; `/api/v1/files/upload_base64` allows 28 MiB. These limits apply to the entire encoded request, not the decoded file. Individual file validation remains the responsibility of the upload handler.

Requests exceeding the limit receive JSON with status 413. Invalid or duplicate Content-Length headers receive status 400. Bodies are buffered in a spooled temporary file and replayed only after the full size is known.

Declared lengths must match the received body; mismatches receive400 before dispatch. Missing lengths are allowed and counted while reading. Temporary files close on rejection, disconnect or handler failure. Spool writes and reads run in the thread pool after the1MiB memory threshold, so disk rollover does not block the event loop. CORS wraps the limiter, preserving allowed-origin headers on errors and normal preflight handling. These are per-request limits, not a concurrency or request-timeout policy.
