import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def test_launcher_end_to_end(tmp_path):
    runtime = tmp_path / 'runtime'
    hostile = tmp_path / 'hostile.db'
    hostile.write_bytes(b'untouched')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, DB_PATH=str(hostile), DATABASE_URL='postgresql://invalid', GEMINI_API_KEY='hostile', RENDER='1')
    command = [sys.executable, '-m', 'gigamind.cli.demo_server', '--runtime-dir', str(runtime), '--port', str(port)]
    with (tmp_path / 'log').open('w+') as log:
        proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            url = f'http://127.0.0.1:{port}'
            for _ in range(1200):
                if proc.poll() is not None:
                    log.seek(0)
                    raise AssertionError(log.read())
                try:
                    with urlopen(url + '/health/ready', timeout=1) as response:
                        assert json.load(response)['status'] == 'ready'
                    break
                except URLError:
                    time.sleep(.1)
            else:
                raise AssertionError('server did not become ready')
            key = (runtime / 'admin-key').read_text().strip()
            assert runtime.stat().st_mode & 0o777 == 0o700
            assert (runtime / 'admin-key').stat().st_mode & 0o777 == 0o600
            def get(path):
                with urlopen(Request(url + path, headers={'Authorization': 'Bearer ' + key}), timeout=3) as response:
                    return json.load(response)
            stats = get('/api/v1/stats')
            assert stats['total_memories'] == 64
            assert stats['total_chat_logs'] == 15
            assert get('/api/v1/review/context?query=unrelated')['rules']
            assets = list((runtime / 'dist/assets').glob('*.js'))
            assert any('Synthetic demo' in f.read_text() for f in assets)
            assert hostile.read_bytes() == b'untouched'
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=15)
    assert subprocess.run(command, cwd=ROOT, env=env, capture_output=True).returncode != 0
    assert hostile.read_bytes() == b'untouched'


def test_refuses_symlink(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(target, target_is_directory=True)
    result = subprocess.run([sys.executable, '-m', 'gigamind.cli.demo_server', '--runtime-dir', str(link / 'demo')], cwd=ROOT, capture_output=True)
    assert result.returncode != 0
    assert not (target / 'demo').exists()
