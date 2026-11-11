# Synthetic demo corpus

This isolated dataset describes fictional projects and fictional assistant preferences. It is not a profile of the operator. It includes 64 legacy memories, 15 conversations, approved knowledge with evidence, pending proposals, and a superseded decision. Source memories are pending indexing; no embeddings or provider calls are made. The labeled queries in `fixtures/demo/corpus.json` test lexical retrieval only, not semantic retrieval quality. Global rules and project rules are queried in their respective scopes.

From the repository directory, an operator can create a **new** local database and start the application with their own API key:

```sh
PYTHON_DOTENV_DISABLED=1 DATABASE_URL='' DB_PATH=/tmp/unused.db python -m gigamind.cli.demo --db /tmp/gigamind-synthetic-demo.db
PYTHON_DOTENV_DISABLED=1 DATABASE_URL='' DB_PATH=/tmp/gigamind-synthetic-demo.db GIGAMIND_API_KEY='<operator-provided-key>' uvicorn gigamind.main:app --host 0.0.0.0 --port 8000
```

Choose another nonexistent path for each new corpus. The command refuses existing files and production environments. Source indexes await a real configured provider and normal indexing; no provider credentials are supplied by the demo. Legacy dashboard records and approved context knowledge are separate application surfaces.
