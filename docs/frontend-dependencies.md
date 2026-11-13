# Frontend dependencies

The frontend uses Vite 8, Vitest 5, and the Vite React plugin 6. Vitest 5 requires Node.js 22.12 or newer on the Node 22 line and Vite 6.4 or newer; Vite 8 requires Node.js 20.19 or newer or 22.12 or newer. The repository, Docker build and CI are verified with Node 22.23.4 and npm 10.9.9; use those pinned versions for the combined toolchain. React remains on version 18.

Install from `frontend/package-lock.json` with `npm ci` in `frontend`. After changing dependencies, run `npm ci`, `npm test`, `npm run build`, and `npm audit` there. Commit the lockfile with dependency changes so clean installs use the verified tree.

See the [Vitest migration guide](https://vitest.dev/guide/migration/) and [Vite 8 release notes](https://v8.vite.dev/blog/announcing-vite8) for compatibility and migration details.

The Vite development server forwards `/api`, `/mcp`, `/openapi.json`, and `/health` to `http://127.0.0.1:8000`. Start the backend separately with its normal credentials. Set `GIGAMIND_DEV_API_ORIGIN` when using a different backend address. The dashboard's advertised MCP and OpenAPI links therefore work through the development origin. Authentication is enforced by the backend. The development proxy does not start a backend or replace its authorization configuration.

`tests/test_dev_proxy.py` starts owned loopback backend and Vite processes, transforms the React entry and CSS, checks public readiness/OpenAPI and rejected unauthenticated API/MCP calls, then initializes a real MCP SDK session through Vite. The default backend test workflow needs a clean `npm ci --prefix frontend` first. No browser or vendor-host acceptance is claimed by this HTTP check.
