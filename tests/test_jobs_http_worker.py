import os
import signal
import subprocess
import sys
import time


def test_http_and_worker(tmp_path):
    env = os.environ.copy()
    env.update(PYTHON_DOTENV_DISABLED="1", DATABASE_URL="", DB_PATH=str(tmp_path / "jobs.db"), GIGAMIND_API_KEY="test-admin-key")
    script = '''
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
'''
    subprocess.run([sys.executable, "-c", script], env=env, check=True)
    cmd = [sys.executable, "-m", "gigamind.cli.worker"]
    subprocess.run(cmd + ["--once"], env=env, check=True)
    verify = '''
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
'''
    subprocess.run([sys.executable, "-c", verify], env=env, check=True)
    subprocess.run(cmd + ["--once"], env=env, check=True)
    for option in ("--poll-seconds", "--lease-seconds"):
        assert subprocess.run(cmd + [option, "nan"], env=env).returncode != 0
    proc = subprocess.Popen(cmd + ["--poll-seconds", "10"], env=env)
    time.sleep(2)
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=10) == 0
