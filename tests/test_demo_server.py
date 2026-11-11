import json
import os
import re
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]


def test_launcher_end_to_end(tmp_path):
    runtime = tmp_path / "runtime"
    hostile = tmp_path / "hostile.db"
    hostile.write_bytes(b"untouched")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(
        os.environ,
        DB_PATH=str(hostile),
        DATABASE_URL="postgresql://invalid",
        GEMINI_API_KEY="hostile",
        RENDER="1",
    )
    command = [
        sys.executable,
        "-m",
        "gigamind.cli.demo_server",
        "--runtime-dir",
        str(runtime),
        "--port",
        str(port),
    ]
    with (tmp_path / "log").open("w+") as log:
        proc = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
        )
        try:
            url = f"http://127.0.0.1:{port}"
            for _ in range(1200):
                if proc.poll() is not None:
                    log.seek(0)
                    raise AssertionError(log.read())
                try:
                    with urlopen(url + "/health/ready", timeout=1) as response:
                        assert json.load(response)["status"] == "ready"
                    break
                except URLError:
                    time.sleep(0.1)
            else:
                raise AssertionError("server did not become ready")
            key = (runtime / "admin-key").read_text().strip()
            assert runtime.stat().st_mode & 0o777 == 0o700
            assert (runtime / "admin-key").stat().st_mode & 0o777 == 0o600

            def get(path):
                with urlopen(
                    Request(url + path, headers={"Authorization": "Bearer " + key}),
                    timeout=3,
                ) as response:
                    return json.load(response)

            with urlopen(url + "/dashboard", timeout=3) as response:
                html = response.read().decode()
                assert response.status == 200
            asset = re.search(r'src="([^"]+\.js)"', html).group(1)
            with urlopen(urljoin(url + "/dashboard", asset), timeout=3) as response:
                assert b"Synthetic demo" in response.read()
            try:
                urlopen(url + "/api/v1/stats", timeout=3)
                assert False, "unauthenticated request succeeded"
            except HTTPError as exc:
                assert exc.code in (401, 403)
            stats = get("/api/v1/stats")
            assert stats["total_memories"] == 64
            assert stats["total_chat_logs"] == 15
            assert get("/api/v1/review/context?query=unrelated")["rules"]
            assets = list((runtime / "dist/assets").glob("*.js"))
            assert any("Synthetic demo" in f.read_text() for f in assets)
            assert hostile.read_bytes() == b"untouched"
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=15)
        log.seek(0)
        assert key not in log.read()
    assert (
        subprocess.run(command, cwd=ROOT, env=env, capture_output=True).returncode != 0
    )
    assert hostile.read_bytes() == b"untouched"


def test_refuses_symlink(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gigamind.cli.demo_server",
            "--runtime-dir",
            str(link / "demo"),
        ],
        cwd=ROOT,
        capture_output=True,
    )
    assert result.returncode != 0
    assert not (target / "demo").exists()


def test_stop_during_spawn_reaps_owned_group(tmp_path, monkeypatch):
    from gigamind.cli import demo_server

    handlers = {}
    signals = []
    waits = []

    class Child:
        pid = 43210

        def wait(self, timeout=None):
            waits.append(timeout)
            if timeout is not None:
                raise subprocess.TimeoutExpired('child', timeout)
            return -signal.SIGKILL

    def spawn(*args, **kwargs):
        env = kwargs['env']
        assert 'HTTP_PROXY' not in env and 'GEMINI_API_KEY' not in env
        assert env['npm_config_offline'] == 'true'
        for name in ('npm_config_userconfig', 'npm_config_globalconfig'):
            assert Path(env[name]).read_text() == ''
            assert Path(env[name]).parent == tmp_path / 'runtime'
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        return Child()

    monkeypatch.setattr(sys, 'argv', ['demo', '--runtime-dir', str(tmp_path / 'runtime')])
    monkeypatch.setattr(demo_server.signal, 'signal', lambda sig, fn: handlers.update({sig: fn}))
    monkeypatch.setattr(demo_server.subprocess, 'Popen', spawn)
    monkeypatch.setattr(demo_server.os, 'killpg', lambda pid, sig: signals.append((pid, sig)))
    assert demo_server.main() == 128 + signal.SIGTERM
    assert signals == [(43210, signal.SIGTERM), (43210, signal.SIGKILL)]
    assert waits == [3, None]
