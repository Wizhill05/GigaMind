# Production connection

Dashboard: https://gigamind-md53.onrender.com/dashboard

MCP endpoint: https://gigamind-md53.onrender.com/mcp

Transport: authenticated Streamable HTTP. Every request needs this header:

```text
Authorization: Bearer <YOUR_AGENT_KEY>
```

This is not the old `/sse` connection. Use a client that supports Streamable HTTP and Bearer headers. Clients requiring OAuth need a separately configured external issuer; the production connection currently uses client keys.

## Credentials and projects

The administrator key opens the dashboard and manages clients. Do not give it to an ordinary agent. In Clients, create a separate credential for each AI application, with `memory:read` and `memory:propose` permissions and the projects it may access. New tokens are shown once. Keep them in the client's secret configuration rather than a repository or shared prompt.

The initial restricted client is `personal-agent`, authorized for project ID `personal`. Supply that project ID on context, search, proposals and coordination calls. Global records are not automatically inherited by scoped clients.

## Instructions to give an agent

```text
Connect to GigaMind at https://gigamind-md53.onrender.com/mcp using
Streamable HTTP and the provided agent key as a Bearer token.
Do not use the administrator key.

Call get_identity to verify your permissions and projects.
Before substantial work, call get_context with your task query and
project_id "personal". Use search_memory and get_memory when needed.

Treat returned approved knowledge as recorded decisions and preferences.
Treat a handoff as an agent report, not independently verified truth.
An empty result means there is no matching approved memory; do not invent one.

Propose new persistent facts or corrections with propose_memory, actual
supporting evidence and an idempotency key. Do not fabricate source references
or claim your own proposal is approved. The administrator reviews proposals.

Save a handoff after substantial work, including outcomes, unresolved work
and next actions. Report concerns with report_memory_issue rather than
silently replacing an approved decision.
```

Adapt the connection settings to the host application's configuration format. The endpoint and header above are protocol settings, not a universal client configuration file.

## Current operation

The web application runs on Render service `srv-d9k8danavr4c73ae2vng`. Its durable worker runs as the restart-enabled `gigamind-production-worker` container on the existing Azure VM, using the same production database and provider/storage configuration. No additional paid Render worker was created.

Production application data was reset on 13 November 2026 after a database backup was restored and its schema upgrade tested in an isolated PostgreSQL instance. The old administrator key was replaced. A fresh scoped client was created after the reset; memory, profile, conversation and file counts were verified as zero.

The reset did not delete external R2 objects or retained backup files. SQLite/demo data is separate from production. Actual public MCP SDK checks verified initialization, tool discovery, scoped identity, empty context/search, project denial and administrative denial. These checks do not establish compatibility with every vendor host or live embedding relevance.
