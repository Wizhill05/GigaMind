GigaMind memory engine review, 10 November 2026

Reviewed commit `65bb48cc8f4e80b4d0abd05d63a360fad07c2c94` on `main`. `git pull --ff-only` reported that the checkout was already current.

My recommendation: keep the application and its existing stack, but do not make this version the authoritative memory server for all your agents. Its main weakness is that it cannot yet reliably distinguish an agent's assertion from a fact you have approved. There are also reproducible authentication, deletion, and retrieval failures. More data will help evaluate it, but it will expose these failures rather than solve them.

This is an assessment, not an implementation pass. Application source was not changed.

1. What exists and what was verified

The application has a React dashboard, a FastAPI REST API, manually implemented JSON-RPC/SSE endpoints, SQLModel database tables, Gemini embeddings, optional external reranking, R2 attachments, document indexing, and chat export importers. PostgreSQL has native vector columns added through startup SQL; SQLite is a development alternative. These are useful building blocks.

Despite the README's wording, `main.py` does not instantiate FastMCP or implement a stdio server. Installing `mcp` is different from using its protocol implementation. The dashboard is principally a record browser and search client. It is not yet a review console for agent-written knowledge.

Verification performed:

- `npm ci --no-audit --no-fund` and `npm run build` passed. TypeScript compilation and the Vite production build succeed.
- A clean backend import failed with `NameError: name 'Any' is not defined` in `embedding.py:74`. The file imports `Dict` but not `Any`.
- Pytest collection failed in all three Python test modules on that same import error. There was no successful execution of the existing suite.
- To inspect subsequent behavior without changing source, a separate probe process supplied the missing annotation name in that module's namespace. It then used FastAPI TestClient, a temporary SQLite database, no production credentials, disabled dotenv loading, and a deterministic embedding substitute for storage/retrieval behavior checks.
- These probes establish application behavior, not Gemini semantic quality or PostgreSQL query performance. PostgreSQL-specific findings below come from source inspection. I did not connect to production services, seed your actual memory store, or perform an interactive browser session.

The recorded probe observations are in [2026-11-10-evidence.json](./2026-11-10-evidence.json). Temporary reproduction code is `/tmp/gigamind-audit/probe.py`; its environment is `/tmp/gigamind-audit-venv`. Temporary paths are local review aids, not a permanent test suite.

2. Fix these before connecting agents

| Priority | Finding and evidence | Required result |
|---|---|---|
| P0 | Backend startup fails at `gigamind/services/embedding.py:74` because `Any` is undefined. Reproduced on Python 3.13; the Dockerfile uses Python 3.11, which also evaluates these annotations. | Clean container startup and test collection must pass in CI. |
| P0 | `/messages` and `/sse` have no authentication dependency. An unauthenticated `tools/call` persisted a profile rule, without even establishing an SSE session. See `gigamind/main.py:322` and `:355`. | Authenticate every MCP request; enforce caller permissions inside the shared service layer; bind transport sessions to callers where sessions are used. |
| P0 | REST authentication accepts any string starting with `gm_at_`. A forged token received HTTP 200 on `/api/v1/stats`; no token received 401. See `main.py:78`. | Validate actual issued credentials, expiry, revocation, audience, and scope. Remove prefix-based acceptance. |
| P0 | `/oauth/token` ignores the return value of code consumption and issues a token for an invalid code or an unknown grant type. Both reproduced. `services/oauth.py` also does not validate the supplied client and redirect against the stored code. | Replace the incomplete OAuth implementation with a supported authorization implementation. Test invalid, expired, reused, mismatched-client and mismatched-redirect codes, plus PKCE and refresh flows. |
| P0 | `delete_memory` and `reset_all_memories` never commit their memory-table changes. Delete returned true but the record survived. Reset reported 71 purged, with 71 still present. See `services/memory.py:914` and `:950`. | Commit the intended database transaction; verify through a new session and after restart. |
| P0 | Cleanup of file indexes commits separately, and object deletion occurs separately from memory deletion. Reset deletes all file indexes, even for files outside memory attachments. A linked file can be shared by multiple memories. | Define attachment ownership explicitly. Delete links independently; garbage-collect unreferenced objects through retryable jobs after the authoritative change commits. Never remove another record's shared attachment. |
| P1 | `search_memory` accepts `category` and `source_agent` but does not apply them to memory/profile candidate selection. A memory excluded by both requested filters was returned. See `services/memory.py:58`. | Apply scope and permission predicates in every candidate query before ranking, including fallback paths. Test isolation with similar records in different projects. |
| P1 | Updating content changes `embedding_json`, but not PostgreSQL `embedding_vector`; it also does not rebuild existing child chunks. The probe confirmed three old chunks remained after replacing their parent text. See `services/memory.py:1001`. | Version the source, rebuild its derived chunks and vectors, and switch search visibility consistently. Old revisions must be unavailable to normal retrieval. |
| P1 | SQLite memory retrieval ignores stored memory vectors and scans at most 60 rows for keyword matches. A matching record inserted after that boundary was absent. An identical stored vector with no lexical overlap also returned nothing. | Provide real local semantic retrieval, or label local mode as lexical-only. Use a full-text index over the corpus rather than an arbitrary initial-row scan. |
| P1 | Conversation search filters PostgreSQL candidates after its global top-40 selection. A relevant project's transcript can be excluded before its filter runs. | Filter before candidate limits; verify recall with competing projects in the same database. |
| P1 | Memory listing and statistics count parent records and their chunks together. Stats load every table into application memory, including transcripts and vectors. | Separate logical memories from chunks; use database aggregates and bounded list queries. |

Also remove the usable default master password in production, restrict CORS, avoid query-string credentials, validate upload sizes and search limits, and escape OAuth form values. The current authorization page interpolates query values directly into HTML. Combine that with a master key stored in localStorage and the impact is larger than a cosmetic form bug. These are source findings, not browser exploit tests.

3. Why the React application feels unfinished

I found concrete application-state problems, rather than a build failure in React itself:

- `frontend/src/api.ts` frequently converts HTTP failures into `null`. `App.tsx:83` and `:95` ignore mutation results and show success anyway. A provider failure can become a false "saved" notification.
- `MemoryModal.tsx:111` calls an asynchronous save through a callback typed to return `void`, then immediately closes. RuleModal follows the same pattern. Preserve the draft and keep the dialog open until success; show the actual error and prevent duplicate submission while pending.
- Saving a memory or rule refreshes stats only. The active tab owns a separate list and gets no invalidation signal. The top-level refresh button also refreshes stats only. This explains changes seeming absent until you switch tabs or reload.
- Tabs can fetch before authentication is complete and do not consistently refetch after login. A successful login can leave a mounted tab with the result of its previous unauthorized request.
- Memory text filtering searches the currently loaded ten records, not the repository. Make that a server-side search, reset pagination when filters change, and show accurate totals.
- Search calls have no cancellation or stale-response protection. A slower response to an old query can overwrite a newer result. The command palette's 150 ms debounce can also cause repeated embedding calls while typing.
- File upload and reindex views refresh after fixed delays. A 1.5-second timer cannot establish that background indexing finished. Poll a real job status or subscribe to progress until completion or failure.
- A backend outage is treated as an invalid master password because `loadStats` uses any null response as an authentication failure. Separate unauthorized, unavailable, rate-limited, empty, and indexing states.
- The transcript import screen defaults to a Windows path, but `/import_path` reads the server's filesystem. That cannot read your laptop's Downloads folder from Azure. Make browser upload the primary action; restrict or remove arbitrary server-path import from the web API.
- The vectorized badge checks whether JSON embeddings exist, not whether PostgreSQL's search vector was successfully written. Show searchable revision and index status instead.

Use one typed API error contract and shared query invalidation. A query library is a reasonable implementation choice, but the important behavior is that successful mutations update every affected view and failures remain visible. Generate frontend API types from the backend schema. Browser-level verification should cover save failure, save success, login recovery, refresh, search across pages, and an indexing job that takes longer than the old timers.

4. The memory model your trust requirement needs

The crucial change is to separate evidence from accepted knowledge. Right now an agent can call `set_profile_rule` and replace your current preference without retaining the old value or the reason. `source_agent` is free-form caller-supplied text, not authenticated provenance. Asking an agent to pass `user_confirmed=true` is also not independent proof that you approved anything.

Keep raw messages and documents as evidence. Extract proposed facts into a separate reviewable representation. Make only accepted facts and explicitly trusted rules eligible for authoritative context by default.

For each memory, store:

- Stable ID, current revision, kind, subject/key, statement, and project or global scope.
- Status such as proposed, accepted, rejected, superseded, expired, or deleted.
- Evidence references to source message IDs or document offsets, including user-versus-assistant authorship.
- Authenticated writer identity and client/session identity, alongside any claimed model name.
- Source timestamp, ingestion timestamp, validity dates where applicable, and optional expiry.
- Who approved it and when, a supersession reference, and a complete revision history.
- A confidence estimate only if its meaning is defined. An agent's confidence or a cosine score is not proof that the fact is true.

Have separate representations for stable preferences, project decisions, temporary task state, and source transcripts. They have different retention and authority rules. `TaskSessionItem` currently exists as a table and count but lacks a usable task handoff lifecycle.

If an agent says "Aryan now prefers Python" while your accepted rule says TypeScript, create a conflict proposal showing both statements and their evidence. Do not silently choose the newest assertion. User-approved changes should supersede the old rule while retaining its history. A project preference should override a global default only within that project.

Use revision checks on updates and idempotency keys on writes. Two agents writing at once should produce a visible conflict or an intentional merge, and a retry should not create another fact. Add deterministic exact deduplication before similarity-based duplicate suggestions. Never auto-merge contradictory statements because their embeddings are similar.

5. Build the dashboard around review and correction

The highest-value new screens are:

- A proposal inbox showing the proposed statement, exact evidence, source role, affected project, conflicting accepted memories, and approve/edit/reject actions. Batch-review harmless proposals while requiring explicit review for persistent behavioral rules.
- A memory detail view with revisions, source links, validity, approval state, related decisions, and restore/supersede actions.
- Agent access management with one credential per client, project restrictions, read-only versus propose-write permissions, revocation, and last-use information. Keep administrative deletion and approval out of normal agent credentials.
- An activity history showing which authenticated client searched, proposed, approved, changed, or deleted records. Minimize sensitive raw query logging and make retention deliberate.
- A retrieval inspector showing why a result was eligible, the matched evidence span, source date, ranking components, index revision, and why conflicting or expired records were excluded.
- An ingestion queue showing parsed, indexed, failed, retrying, and unsupported files with actionable errors.

For your first usable release, prioritize proposal review, provenance, revision history, and project scope over another analytics panel or a graph visualization.

6. Make retrieval useful across your actual history

`scope="all"` currently combines memories, profiles, and files. Conversations have a separate search function, so the main search and command palette do not search all knowledge. Imported conversation embeddings are mostly a title, summary, and first user preview. On-demand vectorization uses the first four short message previews. A decision near the end of a long chat is largely invisible to semantic retrieval.

Index conversation segments across the entire transcript, preserving speaker, turn ID, timestamp, and source references. Return the matching span with a way to fetch neighboring turns. Do not return whole transcripts by default. Preserve ChatGPT branch order by walking the selected conversation branch instead of iterating every node in `mapping.values()`.

Use lexical retrieval and vector retrieval as independent candidate sources, then fuse and optionally rerank them. Exact identifiers, error strings, filenames, and negations need lexical coverage. The current local reranker is a hand-written phrase/term heuristic; it is not a neural cross-encoder or a corpus-IDF BM25 implementation despite the surrounding descriptions. Label it accurately and evaluate it before replacing it.

Add explicit no-match behavior, calibrated relevance thresholds, project filters, accepted-only retrieval, temporal rules, and a context token budget. Return the record ID, revision, provenance, approval state, date, and matched span. The current formatted MCP text omits memory IDs, making precise follow-up updates and citations harder.

Persist raw memory before relying on external embedding availability. A failed provider should leave a recoverable pending-index record rather than lose the user's write. Keep lexical retrieval available during embedding outages. Tag vectors with model, dimension, and source revision; never silently mix embedding spaces.

The document pipeline currently embeds the entire binary before completing its chunk indexing. Google documents a six-page limit per PDF request and an 8,192-token input limit. Split PDFs into supported page groups, preferably individual pages where practical, and make visual anchors correspond to actual page content. The current non-image page chunks contain extracted text, which cannot represent a diagram that extraction missed. Normalize or reject unsupported image formats. See [Google's embedding documentation](https://ai.google.dev/gemini-api/docs/embeddings).

7. Make the MCP contract dependable

Replace the manual JSON-RPC dispatcher with a supported MCP SDK server, using a pinned compatible version. Offer Streamable HTTP for remote clients and implement stdio only if you need it. Retain legacy SSE only for clients you have verified require it. Do not echo an arbitrary requested protocol version as though it were supported.

The current search response uses a custom `structured` key. MCP defines `structuredContent`; define output schemas and return typed results plus readable text, with IDs and citations. Use shared validated request models for REST and MCP so MCP cannot bypass the REST validation rules. Handle tool errors, cancellation, deadlines, notifications, and resource limits through the SDK. Verify real client handshakes rather than only POSTing directly to `/messages`. See the [MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools), [transport specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/streamable-http.mdx), and [authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).

A small agent-facing tool set would be easier to use reliably:

- `get_context`: accepted rules, relevant project decisions, and latest handoff within a token budget.
- `search_memory`: scoped, temporal search with evidence and explicit no-match behavior.
- `get_memory`: retrieve an exact record or a cited source span.
- `propose_memory`: submit evidence-backed knowledge without granting approval authority.
- `save_handoff`: task progress, verified outcomes, unresolved problems, and next actions.
- `report_memory_issue`: flag stale, contradictory, or incorrect context.

Keep approve, restore, credential management, and bulk deletion in a separately authorized administrative interface. Tool annotations help clients present operations, but they do not replace server-side authorization.

An MCP connection alone will not make every AI automatically search or save. Each host needs a tested instruction or hook for task startup and handoff. The bundled SKILL.md is guidance, not an enforcement mechanism. Update it to distinguish source evidence, approved facts, and proposals. Treat retrieved documents as untrusted data, not instructions capable of redefining agent permissions. Its zero-persistence language also cannot enforce external provider retention; make actual data flows clear, including embedding and optional reranking providers.

8. Add representative data with known expected answers

Do not bulk-import all your personal history into the current version. Start with an isolated demo project or database and explicit dataset IDs. Every fixture should have a traceable origin and deterministic cleanup. Existing cleanup code guesses test data from categories, tags, filenames, and even the source agent `researcher`; that is unsuitable for a shared real-data database.

Build a proposed fixture pack containing roughly 150 logical memories across several projects, 20 long conversations, and 15 documents. Include approved preferences, stale rules, contradictions, retries, two simultaneous agent updates, sensitive records outside the permitted scope, deleted records, unrelated distractors, non-English text, code identifiers, and long transcripts with key facts near the end. Include a PDF longer than six pages, a scanned page, an image in an unsupported input format, and a corrupt upload. These are suggested fixture sizes, not measured application capacity.

Pair the dataset with a versioned set of questions and expected source IDs. Include cases such as:

- "Which stack did I choose for this project?" must select the accepted project decision over a global default.
- "What did we decide at the end of that chat?" must find a late transcript span.
- "What is my current preference?" must exclude a superseded rule and expose unresolved conflicts.
- A fabricated answer absent from all sources must produce no evidence, not an arbitrary nearest match.
- Agent A must not receive project B's restricted evidence, even if it is the closest vector match.
- A corrected or deleted fact must not reappear from stale child chunks, retries, or reimports.

After those pass, import a small, personally selected sample of your real history into a separate review queue. Preview extraction before accepting facts. Avoid promoting assistant speculation into personal truth. The CLI importer currently identifies candidate facts through words such as "prefer" or "project"; that can ingest hypothetical and negated text as fact. The API importer behaves differently and primarily stores transcripts. Unify both behind one ingestion path.

There is also a reproduced input bug: a generic single-conversation JSON object supplied as a string reports success with zero imported conversations. Normalize decoded JSON into the expected list and reject or explain unsupported input rather than returning a misleading success. Add resumable import jobs with progress and per-record failure reporting so one provider failure does not make a partially completed import opaque.

9. Operational work needed for a main memory service

Keep FastAPI, PostgreSQL/pgvector, React, and optional R2. A new database family or distributed system is not required to solve the failures found here.

- Replace startup `ALTER TABLE` loops with versioned migrations. PostgreSQL DDL exceptions can abort the transaction, and logging the error does not prove the required schema exists. Verify schema readiness before serving.
- Make source records and their index state transactional. Store embeddings once; long-memory PostgreSQL insertion currently generates chunk embeddings again for the vector update.
- Use durable jobs for imports, indexing, reindexing, and attachment cleanup. FastAPI in-process background tasks do not survive a restart. Include retries, job leases, per-item progress, and visible terminal failures.
- Avoid blocking provider requests inside the async MCP dispatcher. Apply concurrency limits, provider timeouts, backoff with jitter, and cancellation. A single slow indexing call should not stall unrelated MCP requests.
- Pin Python dependencies and use reproducible frontend installation. Render's build command currently has `|| true`, allowing frontend failures to be hidden. Fail the deployment when a required build fails.
- Add liveness and readiness endpoints, structured logs, request/job IDs, index backlog visibility, provider-failure counters, and retrieval tracing with privacy-conscious retention.
- Provide a full backup and restore path. The current export includes memory records, not a complete backup of profiles, conversations, attachments, object data, access configuration, or future revision history. Test restoration into a fresh database, including source-to-attachment relationships.
- Add retention, deletion tombstones, and an import ledger so an old export does not resurrect something intentionally forgotten. Document the backup-retention implications of deletion.

10. Delivery order and acceptance criteria

First, repair correctness: startup, authentication, OAuth, deletion commits, filter enforcement, vector/chunk updates, and truthful UI mutation states. Acceptance means unauthorized requests fail on both protocols, an edited fact replaces old retrieval results, and deletion remains effective across new sessions and restarts.

Second, implement the trust model: authenticated client identity, project scope, proposals, accepted facts, evidence, revisions, conflicts, idempotency, and review controls. Acceptance means a normal agent credential cannot silently replace an approved rule, fabricate approval, or access another scope.

Third, make recall useful: complete transcript segmentation, lexical/vector candidate fusion, source fetching, context budgets, and no-match behavior. Run the labeled fixture pack against both the local supported mode and PostgreSQL. Measure expected-source recall and irrelevant context with the actual configured embedding model. Deterministic provider substitutes remain useful for transaction tests but cannot establish semantic quality.

Fourth, validate adoption and recovery: use two different agent clients, start a task in one, resume it in another, correct a remembered rule, revoke one client, restart the service during ingestion, and restore a backup into a fresh instance. The user-visible facts and their provenance must remain consistent throughout.

Only then enable gradual daily use. Begin with read access to approved memory and proposal-only writes. Expand automatic acceptance only for narrowly defined facts whose evidence and failure modes you have evaluated. Your practical adoption gate is being able to answer "why does the AI believe this, who changed it, and how do I correct it everywhere?" from the application itself.
