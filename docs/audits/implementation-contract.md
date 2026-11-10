Implementation contract for the 2026-11-10 review

All findings in 2026-11-10-memory-engine-review.md are in scope. Work occurs in isolated delegated checkouts and is integrated only after parent review. Do not deploy, push, touch real cloud data, or introduce real personal fixture data.

Wave one ownership:
- Security/MCP: gigamind/main.py, gigamind/services/oauth.py, new gigamind/security.py and protocol modules, requirements.txt, .env.example, security/protocol tests.
- Memory/trust: gigamind/db/**, gigamind/services/memory.py, new trust service/router modules and their tests. Do not edit main.py. Provide a mountable APIRouter in gigamind/routers/review.py exposing router.
- Frontend: frontend/**, frontend behavior tests. Do not redesign the existing visual style.

Shared auth contract: gigamind/security.py exposes Actor with id, scopes (set[str]), project_ids (set[str] or None meaning all), is_admin; get_actor as FastAPI dependency accepting Bearer credentials; require_scope(*scopes) dependency returning Actor. Admin master credentials have all rights. Agent credentials must be server-managed, revocable and project scoped; claimed source_agent is never identity. Scope names memory:read, memory:propose, memory:write, memory:approve, memory:delete, admin. Service authorization must also protect MCP.

Review REST contract, admin master key remains supported:
GET /api/v1/review/proposals?project_id=... -> {proposals: [...], total: n}
POST /api/v1/review/proposals -> content, category, tags, project_id optional, evidence list, kind (fact/preference/decision), subject optional, idempotency_key required -> {proposal: ...}
POST /api/v1/review/proposals/{id}/resolve -> {action: approve|reject, content optional, expected_revision integer} -> {proposal: ..., memory: ... optional}
GET /api/v1/review/memories/{id}/history -> {revisions: [...]}
POST /api/v1/review/memories/{id}/restore -> {revision: integer, expected_revision: integer} -> {memory: ...}
GET /api/v1/review/activity -> {events: [...]}
GET /api/v1/review/context?query=...&project_id=...&token_budget=... -> {rules: [...], memories: [...], handoff: ... optional, citations: [...]}
POST /api/v1/review/handoffs -> {task_name, summary, status, project_id optional, verified_outcomes:[], unresolved:[], next_actions:[]} -> {handoff: ...}
POST /api/v1/review/issues -> {memory_id, reason, project_id optional} -> {issue: ...}
GET/POST /api/v1/admin/clients and POST /api/v1/admin/clients/{id}/revoke, created client returns token once. Client fields name, scopes, project_ids. GET /api/v1/admin/clients -> {clients: [...]}. POST -> {client: ..., token: ...}.

All records include id, revision, status, timestamps and authenticated writer identity where applicable. Proposal evidence is list of {source_type, source_id, quote, source_role optional}; require evidence for agent-originated proposals. Proposal status proposed/accepted/rejected. Accepted memory fields additionally support superseded/expired/deleted. Preserve existing API response fields where feasible. New routes enforce actor scope and project access. API errors use non-2xx status and detail string or documented structured detail; frontend must display these faithfully. Publish schemas/tests; flag necessary contract changes in final agent report.

Wave two: durable ingestion and indexing jobs, complete transcript segmentation and importer unification; backup/restore and forgetting ledger; fixture and retrieval evaluation suite; reproducible CI/deployment/readiness/docs. Parent coordinates any required shared-file integration.
