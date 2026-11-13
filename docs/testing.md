# Testing

Install the backend requirements and test dependencies in a virtual environment:

```sh
python -m pip install -r requirements-test.txt
python -m pytest
```

The pytest configuration disables dotenv, discards inherited database and provider credentials, creates a temporary SQLite database, and blocks external DNS resolution and non-loopback socket connections in the pytest process. Inherited OAuth and proxy settings are also removed. Tests that launch subprocesses must provide their own isolated environment and stub external boundaries. The database is removed when pytest exits. Do not run `tests/cleanup_test_data.py` against a configured database.

The native PostgreSQL migration tests are optional. Start a disposable **local** PostgreSQL service with pgvector installed and a dedicated empty database, then run:

```sh
GIGAMIND_RUN_LOCAL_POSTGRES=1 GIGAMIND_TEST_POSTGRES_URL=postgresql://test:test@127.0.0.1:5432/gigamind_test python -m pytest tests/test_postgres_migrations.py
```

These tests create and drop temporary schemas and may create the vector extension; never point them at a shared database. They reject non-loopback hosts. The deployed edge-case shell script and `tests/run_tests.py` are manual live acceptance tools, not part of pytest; they can write to their configured server. Run them only against a dedicated disposable deployment with explicit authorization. No live provider acceptance suite is enabled by supplying credentials to pytest.

For the frontend:

```sh
cd frontend
npm ci
npm test
npm run build
```

The CI workflow runs the offline backend and frontend commands and the PostgreSQL migration tests against a disposable local pgvector service. It does not publish artifacts or deploy. Offline embedding fixtures verify persistence and retrieval contracts, not semantic relevance or multimodal quality. Live semantic-quality acceptance requires a separate explicitly opted-in live environment; credentials alone never enable it in pytest.

Use Python 3.12.3 and Node 22.23.4 (npm 10.9.9), the versions used for the locked build. `requirements.in` is the direct dependency input; `requirements.txt` pins the complete runtime resolution and `requirements-test.txt` adds pinned test tools. To update, use a new Python 3.12.3 environment and resolve against public PyPI:

```sh
python3.12 -m venv /tmp/gigamind-resolve
/tmp/gigamind-resolve/bin/pip install --index-url https://pypi.org/simple -r requirements.in pytest httpx
/tmp/gigamind-resolve/bin/pip freeze > /tmp/gigamind-resolved.txt
```

Review the resolution, put runtime pins in `requirements.txt` and the test-only pins in `requirements-test.txt` after its `-r requirements.txt` line. Install both into a second clean environment and run this suite. Review upgrades and dependency changes before committing. Platform-specific dependencies may require a new lock and validation.

The Render build uses `scripts/build.sh`; any failed frontend install or build stops the Python installation and fails the build.
