# Authentication

The master API key and locally issued client keys remain supported. External OAuth accepts RS256 JWT access tokens only. GigaMind does not issue tokens or configure an external provider.

Set `GIGAMIND_PUBLIC_URL` to the public HTTPS origin without a trailing slash. Set `OAUTH_ISSUER` to the exact issuer claim, `OAUTH_JWKS_URL` to its HTTPS signing key endpoint, and `OAUTH_AUDIENCE` to the public origin followed by `/mcp`. Configure all four together. For local development only, `OAUTH_ALLOW_LOOPBACK_HTTP=true` allows HTTP loopback addresses; production forbids this exception.

Register the MCP resource audience and required scopes with the external authorization server. Register the OAuth client and redirect URIs with that server according to its documentation. GigaMind does not provide client registration or redirect handling. Tokens must contain a space-separated `scope` claim; effective scopes are the intersection with the local client's scopes. Project access comes from the local client. External identities cannot receive admin access.

Using the master key, create a scoped client at `POST /api/v1/admin/clients`, then bind the exact issuer and subject to its ID at `POST /api/v1/admin/oauth/bindings`. List bindings at `GET /api/v1/admin/oauth/bindings` and revoke one at `POST /api/v1/admin/oauth/bindings/{id}/revoke`. A revoked binding cannot be reactivated or rebound. Revoking either the binding or client blocks subsequent requests.

Protected resource metadata is available at `/.well-known/oauth-protected-resource` and `/.well-known/oauth-protected-resource/mcp` when configured. With OAuth disabled, these return 404 and API keys still work.

Client credentials may have an optional `expires_at` supplied as a future, timezone-aware ISO 8601 timestamp when created. It is stored in UTC. Legacy credentials with no expiry remain valid until revoked. Admin client lists expose creation, expiry, last-use and revision metadata; last use is updated at most once every five minutes.

To rotate a local key, an administrator posts `{"expected_revision": 0}` (using the current client revision) to `/api/v1/admin/clients/{id}/rotate`. The response contains `client` metadata and a new plaintext `token`, shown only once. Rotation immediately replaces the local key and retains the client's permissions, expiry and OAuth bindings. A stale revision, expired client or revoked client returns 409. Revoking the client instead blocks both its local key and all external OAuth bindings; revocation is idempotent.
