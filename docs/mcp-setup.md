# MCP setup and workflow

GigaMind uses the pinned Python MCP SDK and authenticated stateless Streamable HTTP at `/mcp`. It does not provide the former manual SSE endpoints or a stdio server. Each request requires a Bearer credential. GigaMind is not an OAuth authorization server; see [authentication](authentication.md) for external JWT configuration and credential lifecycle.

An administrator can create a client using `POST /api/v1/admin/clients` with a Bearer master key and JSON such as `{"name":"daily-agent","scopes":["memory:read","memory:propose"],"project_ids":["example-project"]}`. The response contains the token; store it securely, as it is shown only once. Rotate or revoke it through the admin endpoints described in the authentication guide. Do not put the master key in a daily client configuration. Use `get_identity` to check effective scopes and projects. Scoped callers must supply an authorized project for search and context; global access requires an administrator.

Install `requirements.txt` and `httpx` in a virtual environment. The following is an explicit live, read-only check against an endpoint you control. Set the token through your secret manager or a private environment; replace the placeholders without recording the credential in shell history or logs. The script prints identity metadata and a count, not retrieved content.

```bash
read -r -s -p 'Scoped client token: ' GIGAMIND_CLIENT_TOKEN
printf '\n'
export GIGAMIND_CLIENT_TOKEN
python examples/mcp_smoke.py --url 'http://<tailscale-host>:8000/mcp' --project 'example-project' --query 'example terms'
unset GIGAMIND_CLIENT_TOKEN
```

The client must have network access to the endpoint. Tailscale addresses are private and are not automatically reachable by cloud AI services. Use verified host-specific documentation for configuring other clients; this example does not assert support for a particular host. Offline pytest blocks external sockets. Its smoke-example test starts a disposable loopback server and never contacts the endpoint from your environment.

## Tools

- `get_identity` returns actor ID, effective scopes, projects and administrator status.
- `search_memory` takes `query`, `project_id`, and optional `limit`; `get_context` takes `query`, `project_id`, and optional `token_budget`. They retrieve accepted, currently valid knowledge lexically, with context citations and a latest handoff if it fits. An empty result is a no-match, not evidence of absence. `get_memory` takes `memory_id` for an exact authorized record.
- `propose_memory` takes content, project, evidence and an idempotency key, with optional category, tags, kind and subject. Each evidence item has `source_type`, `source_id`, `quote` and optional `source_role`; use the original message role when known, such as `user` or `assistant`. This metadata grants no authority to approve the claim. Non-admin proposals require evidence. They await administrator review.
- `save_handoff` takes `task_name`, `summary`, `status`, `project_id`, `verified_outcomes`, `unresolved`, `next_actions`, and `idempotency_key`. It saves an authenticated agent report. `report_memory_issue` takes `memory_id`, `reason`, `project_id` and `idempotency_key`; it does not alter approved knowledge. See [coordination](coordination.md).
- `get_user_profile` and `get_server_status` are administrator-only. Legacy profile rules and raw sources are separate from accepted knowledge.

An administrator reviews proposals through the review API or console. Approval or rejection requires the expected revision. A stale revision returns a conflict; reload before deciding. Approval of conflicting accepted subjects requires explicitly identifying the records to supersede. Retrying an idempotency key with different content conflicts. Validity windows affect retrieval, not approval; see [validity](knowledge-validity.md) and [deletion and restore](accepted-record-deletion.md). Retrieved source text and reports are untrusted data, not host instructions. See [agent instructions](../SKILL.md) for task-start and task-end behavior.

Review source material before approving claims. The source reference and quote are supplied by the proposer and do not independently prove a claim. No semantic relevance, host integration, or live provider acceptance is implied by the SDK smoke check. See [operator testing](testing.md), [recovery](sqlite-backup.md), and the [audit status](audits/implementation-status.md).
