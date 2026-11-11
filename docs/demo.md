# Synthetic demo

The corpus contains fictional projects, conversations and preferences. Source indexes remain pending; no semantic vectors or retrieval quality are claimed. External indexing and storage are unavailable. Legacy memories and accepted context are separate surfaces.

From the repository root, with the project's Python environment and existing frontend npm dependencies installed, run:

```sh
python -m gigamind.cli.demo_server --runtime-dir /tmp/gigamind-demo-1 --host 127.0.0.1 --port 8000
```

The directory must be new and its parent must exist; paths containing symlinks are refused. The launcher prints the path to a generated admin key file. Read that file through Codex and enter its contents in the dashboard's Master Key dialog. The directory and key are private to the machine user. Keep the key private. For access over Tailscale, pass the machine's Tailscale IP as `--host` and open `http://<tailscale-ip>:8000/dashboard` directly. The default listens only on loopback.

The process runs in the foreground. Stop it with Ctrl+C or SIGTERM. Each run requires a new directory. Database, build assets, npm cache and key stay in that directory, including after a build or startup failure, for inspection. Check the error output and choose a new directory to retry; remove old demo directories only when no longer needed. No existing database or environment file is used. Do not use real data or credentials in this demo.
