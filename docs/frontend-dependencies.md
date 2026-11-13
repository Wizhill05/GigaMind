# Frontend dependencies

The frontend uses Vite 8, Vitest 5, and the Vite React plugin 6. Vitest 5 requires Node.js 22.12 or newer on the Node 22 line and Vite 6.4 or newer; Vite 8 requires Node.js 20.19 or newer or 22.12 or newer. Use Node 22.12 or newer on the Node 22 line for the combined toolchain. React remains on version 18.

Install from `frontend/package-lock.json` with `npm ci` in `frontend`. After changing dependencies, run `npm ci`, `npm test`, `npm run build`, and `npm audit` there. Commit the lockfile with dependency changes so clean installs use the verified tree.

See the [Vitest migration guide](https://vitest.dev/guide/migration/) and [Vite 8 release notes](https://v8.vite.dev/blog/announcing-vite8) for compatibility and migration details.
