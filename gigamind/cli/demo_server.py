"""Build and run a private, synthetic offline demo in a new directory."""

import argparse
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def _stop_owned_group(child, timeout=3):
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    # A descendant may outlive the group leader.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait(timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-dir", required=True, help="new directory; its parent must exist"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    path = Path(os.path.abspath(os.path.expanduser(args.runtime_dir)))
    # Refuse symlinks in every existing path component, including dangling links.
    if any(p.is_symlink() for p in (path, *path.parents)):
        parser.error("runtime path must not contain symlinks")
    try:
        path.mkdir(mode=0o700)
    except OSError as exc:
        parser.error(f"cannot create new runtime directory: {exc}")
    os.chmod(path, 0o700)
    key = secrets.token_urlsafe(32)
    keyfile = path / "admin-key"
    fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    for config in ("npm-user-config", "npm-global-config"):
        fd = os.open(path / config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    env = {
        "PATH": os.defpath + ":/usr/local/bin",
        "TMPDIR": str(path),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "DATABASE_URL": "",
        "DB_PATH": str(path / "demo.db"),
        "ENVIRONMENT": "test",
        "GIGAMIND_API_KEY": key,
        "GIGAMIND_STATIC_DIST": str(path / "dist"),
        "GIGAMIND_DEMO_ENV_DIR": str(path),
        "VITE_SYNTHETIC_DEMO": "1",
        "npm_config_cache": str(path / "npm-cache"),
        "npm_config_userconfig": str(path / "npm-user-config"),
        "npm_config_globalconfig": str(path / "npm-global-config"),
        "npm_config_update_notifier": "false",
        "npm_config_offline": "true",
    }
    print(f"Synthetic demo runtime: {path}\nAdmin key file: {keyfile}", flush=True)
    child = None
    stop_signal = None

    def stop(signum, _frame):
        nonlocal stop_signal
        if stop_signal is None:
            stop_signal = signum

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for cmd, cwd in [
            ([sys.executable, "-m", "gigamind.cli.demo", "--db", env["DB_PATH"]], ROOT),
            (
                [
                    "npm",
                    "run",
                    "build",
                    "--",
                    "--outDir",
                    env["GIGAMIND_STATIC_DIST"],
                    "--emptyOutDir",
                    "false",
                ],
                ROOT / "frontend",
            ),
            (
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "gigamind.main:app",
                    "--host",
                    args.host,
                    "--port",
                    str(args.port),
                ],
                ROOT,
            ),
        ]:
            if stop_signal is not None:
                return 128 + stop_signal
            child = subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=True)
            while stop_signal is None:
                try:
                    code = child.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    pass
            if stop_signal is not None:
                return 128 + stop_signal
            child = None
            if code:
                return code
        return 0
    finally:
        if child is not None:
            _stop_owned_group(child)


if __name__ == "__main__":
    sys.exit(main())
