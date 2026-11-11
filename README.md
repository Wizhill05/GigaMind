# GigaMind

GigaMind stores source material and reviewed knowledge for use by AI clients. Its MCP endpoint is authenticated, stateless Streamable HTTP at `/mcp`. Accepted knowledge retrieval is project-scoped and lexical; it is not the legacy vector search pipeline. This is an evolving implementation, not a claim of production, multi-client, or live-provider acceptance. See the [implementation status](docs/audits/implementation-status.md) and [original audit](docs/audits/2026-11-10-memory-engine-review.md) for remaining work.

## Getting started

Install Python dependencies from `requirements.txt`, configure a database and a strong unique `GIGAMIND_API_KEY`, and start `uvicorn gigamind.main:app --host 0.0.0.0 --port 8000`. The placeholder key in `.env.example` is rejected for authentication; replace it. Protect the master key and use it only for administration. See [authentication](docs/authentication.md) and [testing](docs/testing.md).

For a local service on the Azure VM, use its Tailscale hostname and port directly, for example `http://<tailscale-host>:8000/dashboard` and `http://<tailscale-host>:8000/mcp`. A remote client must itself be able to reach that address. Cloud-hosted AI services cannot be assumed to reach a private Tailscale address. A public deployment requires its own appropriate network and authentication configuration.

Create a revocable client credential with explicit project IDs and only `memory:read` and, when needed, `memory:propose`. Use that credential for daily work. [MCP setup](docs/mcp-setup.md) describes the tools, an opt-in Python SDK smoke check, and review workflow. [Agent instructions](SKILL.md) provide task-start and handoff guidance; hosts must actually invoke tools for those instructions to take effect.

## Operations and data

Use `/health/live` and `/health/ready` for liveness and schema readiness. Consult [testing](docs/testing.md), [jobs](docs/jobs.md), [file lifecycle](docs/file-lifecycle.md), and [SQLite backup and restore](docs/sqlite-backup.md) before operating or recovering a deployment. SQLite backup does not include object bytes or secrets; PostgreSQL and cloud object recovery are not implemented there.

Database records, source material, proposals, reports, audit history, and embeddings may persist. File attachments may be stored in configured object storage. Configured external embedding providers receive content for embedding; optional external rerankers receive queries and candidate content. AI hosts receiving tool results can also process or retain that content under their own policies. Do not assume zero persistence or any provider retention guarantee. Review configuration and provider terms before sending sensitive data.

## License

MIT License.
