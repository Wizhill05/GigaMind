import os
import signal
import subprocess
import sys
import time
import selectors


def read_until(process, expected, timeout=10):
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            assert remaining > 0 and selector.select(remaining), (
                "Worker did not signal readiness"
            )
            line = process.stdout.readline()
            assert line, "Worker exited before readiness"
            if line.strip() == expected:
                return


def test_http_and_worker(tmp_path):
    env = os.environ.copy()
    env.update(
        PYTHON_DOTENV_DISABLED="1",
        DATABASE_URL="",
        DB_PATH=str(tmp_path / "jobs.db"),
        GIGAMIND_API_KEY="test-admin-key",
    )
    for name in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_ENDPOINT_URL",
        "GEMINI_API_KEY",
        "GEMINI_API_KEYS",
        "GOOGLE_API_KEY",
        "GOOGLE_API_KEYS",
    ):
        env.pop(name, None)
    script = """
from fastapi.testclient import TestClient
from gigamind.main import app
c = TestClient(app)
a = {"Authorization": "Bearer test-admin-key"}
assert c.get("/api/v1/jobs").status_code == 401
assert c.get("/api/v1/jobs", headers={"Authorization": "Bearer forged"}).status_code == 401
client = c.post("/api/v1/admin/clients", headers=a, json={"name":"limited", "scopes":["memory:read"], "project_ids":["p"]}).json()
assert c.get("/api/v1/jobs", headers={"Authorization":"Bearer " + client["token"]}).status_code == 403
from gigamind.security import create_client
_, spoof = create_client("spoof", ["admin"], ["p"])
assert c.get("/api/v1/jobs", headers={"Authorization":"Bearer " + spoof}).status_code == 403
url = "/api/v1/jobs"
body = {"kind":"index_file", "payload":{"key":"missing"}, "idempotency_key":"one", "max_attempts":1}
r = c.post(url, headers=a, json=body)
assert r.status_code == 200, r.text
job = r.json()
assert "lease_token" not in job
assert c.post(url, headers=a, json=body).json()["id"] == job["id"]
assert c.post(url, headers=a, json={**body, "payload":{"key":"other"}}).status_code == 409
for b in [{**body, "extra":1}, {**body, "payload":{"key":"x", "extra":1}}, {**body, "max_attempts":True}, {**body, "kind":"unknown"}, {**body, "idempotency_key":"x"*256}]:
    assert c.post(url, headers=a, json=b).status_code == 422
assert c.get(url, headers=a, params={"limit":101}).status_code == 422
assert c.get(url, headers=a, params={"offset":-1}).status_code == 422
assert c.get(url + "/unknown", headers=a).status_code == 404
assert c.post(url + "/unknown/cancel", headers=a).status_code == 404
assert c.get(url, headers=a).json()["jobs"][0]["id"] == job["id"]
other = c.post(url, headers=a, json={"kind":"index_file", "payload":{"key":"cancel"}}).json()
assert c.get(url + "/" + other["id"], headers=a).json()["state"] == "queued"
assert c.post(url + "/" + other["id"] + "/cancel", headers=a).json()["state"] == "cancelled"
assert c.post(url + "/" + other["id"] + "/cancel", headers=a).status_code == 409
"""
    subprocess.run([sys.executable, "-c", script], env=env, check=True)
    cmd = [sys.executable, "-m", "gigamind.cli.worker"]
    subprocess.run(cmd + ["--once"], env=env, check=True)
    verify = """
from gigamind.services.jobs import status
from sqlmodel import Session, select
from gigamind.db.database import engine
from gigamind.db.jobs import Job
with Session(engine) as s:
 j = s.exec(select(Job).where(Job.resource_key == "missing")).one()
 assert j.state == "failed" and j.attempts == 1
from fastapi.testclient import TestClient
from gigamind.main import app
c = TestClient(app)
assert c.post("/api/v1/jobs/" + j.id + "/cancel", headers={"Authorization":"Bearer test-admin-key"}).status_code == 409
"""
    subprocess.run([sys.executable, "-c", verify], env=env, check=True)
    subprocess.run(cmd + ["--once"], env=env, check=True)
    for option in ("--poll-seconds", "--lease-seconds"):
        assert subprocess.run(cmd + [option, "nan"], env=env).returncode != 0
    proc = subprocess.Popen(
        cmd + ["--poll-seconds", "10"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    try:
        read_until(proc, b"Worker ready")
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=5) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_worker_finishes_current_job_and_renews_after_sigterm(tmp_path):
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": os.getcwd(),
        "PYTHON_DOTENV_DISABLED": "1",
        "DATABASE_URL": "",
        "DB_PATH": str(tmp_path / "shutdown.db"),
    }
    prepare = """
from gigamind.db.jobs import Job
from gigamind.db.database import init_db
from gigamind.services.jobs import enqueue
init_db()
enqueue('index_file', {'key': 'controlled.txt'})
"""
    subprocess.run([sys.executable, "-c", prepare], env=env, check=True)
    script = """
import sys, signal, threading
from gigamind.services import jobs
from gigamind.cli.worker import main
original_signal = signal.signal
stop_observed = threading.Event()
output_lock = threading.Lock()
def announce(line):
    with output_lock:
        print(line, flush=True)
def observe_stop():
    stop_observed.wait()
    announce('STOP_ACK')
threading.Thread(target=observe_stop, daemon=True).start()
def register(sig, handler):
    def observed(*args):
        handler(*args)
        stop_observed.set()
    return original_signal(sig, observed)
signal.signal = register
original_heartbeat = jobs.heartbeat
def heartbeat(*args, **kwargs):
    renewed = original_heartbeat(*args, **kwargs)
    if renewed: announce('RENEWED')
    return renewed
jobs.heartbeat = heartbeat
def handler(payload, lease):
    announce('HANDLER_STARTED')
    assert sys.stdin.readline().strip() == 'release'
    return {'status': 'completed'}
jobs.HANDLERS['index_file'] = handler
sys.argv = ['worker', '--lease-seconds', '1']
main()
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    try:
        read_until(proc, b"HANDLER_STARTED")
        proc.send_signal(signal.SIGTERM)
        read_until(proc, b"STOP_ACK")
        read_until(proc, b"RENEWED")
        proc.stdin.write(b"release\n")
        proc.stdin.flush()
        assert proc.wait(timeout=5) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    verify = """
from sqlmodel import Session, select
from gigamind.db.database import engine
from gigamind.db.jobs import Job
with Session(engine) as session:
    job = session.exec(select(Job)).one()
    assert job.state == 'completed' and job.attempts == 1 and job.lease_token is None
"""
    subprocess.run([sys.executable, "-c", verify], env=env, check=True)
