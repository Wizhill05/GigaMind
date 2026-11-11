import os
import subprocess
import sys


def test_file_lifecycle_http(tmp_path):
    env = os.environ.copy()
    env.update(PYTHON_DOTENV_DISABLED="1", DATABASE_URL="", DB_PATH=str(tmp_path / "http.db"), GIGAMIND_API_KEY="test-admin-key")
    for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT_URL"):
        env.pop(name, None)
    script = '''
from fastapi.testclient import TestClient
from sqlmodel import Session
from gigamind.main import app
from gigamind.db.database import engine, MemoryItem
import gigamind.main as main
from gigamind.services import jobs
from gigamind.services.storage import storage_service
c = TestClient(app)
a = {"Authorization": "Bearer test-admin-key"}
assert c.post("/api/v1/files/delete", json={"key":"x"}).status_code == 401
limited = c.post("/api/v1/admin/clients", headers=a, json={"name":"limited", "scopes":["memory:read"], "project_ids":["p"]}).json()["token"]
assert c.delete("/api/v1/files/x", headers={"Authorization":"Bearer " + limited}).status_code == 403
assert c.post("/api/v1/files/delete", headers=a, json={"key":" "}).status_code == 422
assert c.post("/api/v1/files/reindex", headers=a, json={"key":"https://example.test/x"}).status_code == 422
with Session(engine) as session:
    session.add(MemoryItem(id="ref", content="ref", media_url="referenced", created_at="now", last_accessed="now"))
    session.commit()
assert c.delete("/api/v1/files/referenced", headers=a).status_code == 409
r = c.post("/api/v1/files/delete", headers=a, json={"key":"x"})
assert r.status_code == 202, r.text
j = r.json()
assert j == {"key":"x", "job_id":j["job_id"], "state":"queued", "cleanup":"pending"}
assert c.delete("/api/v1/files/x", headers=a).json() == j
engine.dispose()
assert jobs.status(j["job_id"]).state == "queued"
assert c.post("/api/v1/files/url", headers=a, json={"key":"x"}).status_code == 409
assert c.get("/api/v1/files/chunks", headers=a, params={"key":"x"}).status_code == 409
assert c.post("/api/v1/files/reindex", headers=a, json={"key":"x"}).status_code == 409
storage_service.is_enabled = lambda: True
storage_service.list_files = lambda **kw: [{"key":"x"}, {"key":"active"}]
storage_service.get_presigned_download_url = lambda **kw: "https://example.test/file"
assert c.get("/api/v1/files", headers=a).json()["files"] == [{"key":"active"}]
main.list_indexed_storage_files = lambda **kw: [{"key":"x"}, {"key":"active"}]
assert c.get("/api/v1/files/indexed", headers=a).json()["files"] == [{"key":"active"}]
assert c.post("/api/v1/files/url", headers=a, json={"key":"active"}).status_code == 200
with Session(engine) as session:
    row = session.get(jobs.Job, j["job_id"])
    row.max_attempts = 1
    session.commit()
storage_service.delete_file = lambda key: False
assert jobs.run_once().state == "failed"
r = c.delete("/api/v1/files/x", headers=a)
assert r.json()["job_id"] != j["job_id"]
storage_service.delete_file = lambda key: True
assert jobs.run_once().state == "completed"
assert c.delete("/api/v1/files/x", headers=a).json()["cleanup"] == "completed"
first = c.post("/api/v1/files/reindex", headers=a, json={"key":"active"}).json()
lease = jobs.claim()
second = c.post("/api/v1/files/reindex", headers=a, json={"key":"active"}).json()
assert first["job_id"] != second["job_id"]
try:
    with Session(engine) as session:
        jobs.JobLease(first["job_id"], lease.lease_token).publication_guard(session)
except jobs.PermanentFailure:
    pass
else:
    raise AssertionError("old publisher was not fenced")
'''
    subprocess.run([sys.executable, "-c", script], env=env, check=True)
