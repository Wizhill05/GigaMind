"""Isolate app startup/auth environment; exercise real HTTP routes, queue and indexer."""

import os
import subprocess
import sys


def test_file_lifecycle_http(tmp_path):
    env = os.environ.copy()
    env.update(
        PYTHON_DOTENV_DISABLED="1",
        DATABASE_URL="",
        DB_PATH=str(tmp_path / "http.db"),
        GIGAMIND_API_KEY="test-admin-key",
    )
    for name in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_ENDPOINT_URL",
        "R2_BUCKET_NAME",
        "GEMINI_API_KEY",
        "GEMINI_API_KEYS",
        "GOOGLE_API_KEY",
        "GOOGLE_API_KEYS",
    ):
        env.pop(name, None)
    script = r"""
from datetime import timedelta
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from gigamind.main import app
from gigamind.db.database import engine, MemoryItem, StorageFileItem, StorageChunkItem
from gigamind.services import jobs, indexing
from gigamind.services.storage import storage_service
indexing.embedding.DEFAULT_DIM = 3
indexing.generate_embedding = lambda **kw: [1., 2., 3.]
a = {"Authorization": "Bearer test-admin-key"}
objects = {"x": b"old source", "active.txt": b"old active source", "forgotten.txt": b"old forgotten source"}
signed = []
deleted = []
class Bucket:
    def list_objects_v2(self, **kwargs):
        return {"Contents": [{"Key":key, "Size":len(data)} for key,data in objects.items()]}
storage_service.s3_client = Bucket()
storage_service.is_enabled = lambda: True
def url(key, **kwargs):
    signed.append(key)
    return "https://example.test/" + key
storage_service.get_presigned_download_url = url
storage_service.download_file = lambda key: objects.get(key)
for key, data in objects.items():
    indexing.index_file_content(key, key if key.endswith('.txt') else 'x.txt', data)
jobs.forget_resource('forgotten.txt')
with TestClient(app) as c:
    assert c.post("/api/v1/files/delete", json={"key":"x"}).status_code == 401
    limited = c.post("/api/v1/admin/clients", headers=a, json={"name":"limited", "scopes":["memory:read"], "project_ids":["p"]}).json()["token"]
    for path, payload in (("/api/v1/files/delete", {"key":"x"}), ("/api/v1/files/reindex", {"key":"active.txt"}), ("/api/v1/files/url", {"key":"active.txt"})):
        assert c.post(path, headers={"Authorization":"Bearer " + limited}, json=payload).status_code == 403
    assert c.delete("/api/v1/files/x", headers={"Authorization":"Bearer " + limited}).status_code == 403
    for invalid in (' ', 'https://example.test/x', 'x\x00y', 'a' * 1025):
        assert c.post("/api/v1/files/delete", headers=a, json={"key":invalid}).status_code == 422
        assert c.post("/api/v1/files/reindex", headers=a, json={"key":invalid}).status_code == 422
    with Session(engine) as session:
        session.add(MemoryItem(id="ref", content="ref", media_url="referenced", created_at="now", last_accessed="now"))
        session.commit()
    assert c.delete("/api/v1/files/referenced", headers=a).status_code == 409
    storage_service.is_enabled = lambda: False
    r = c.post("/api/v1/files/delete", headers=a, json={"key":"x"})
    assert r.status_code == 202, r.text
    j = r.json()
    assert j == {"key":"x", "job_id":j["job_id"], "state":"queued", "cleanup":"pending"}
    assert c.delete("/api/v1/files/x", headers=a).json() == j
    engine.dispose()
    assert jobs.status(j["job_id"]).state == "queued"
    assert jobs.run_once().state == 'retrying'
    assert c.get('/api/v1/jobs/' + j['job_id'], headers=a).json()['state'] == 'retrying'
    with Session(engine) as session:
        assert session.exec(select(StorageFileItem).where(StorageFileItem.key == 'x')).first() is None
        assert session.exec(select(StorageChunkItem).where(StorageChunkItem.file_key == 'x')).first() is None
        row = session.get(jobs.Job, j['job_id'])
        row.max_attempts = row.attempts
        session.commit()
    assert c.post("/api/v1/files/url", headers=a, json={"key":"x"}).status_code == 409
    assert c.get("/api/v1/files/chunks", headers=a, params={"key":"x"}).status_code == 409
    assert c.post("/api/v1/files/reindex", headers=a, json={"key":"x"}).status_code == 409
    storage_service.is_enabled = lambda: True
    assert c.get('/api/v1/files', headers=a).json()['files'][0]['key'] == 'active.txt'
    assert [f['key'] for f in c.get('/api/v1/files/indexed', headers=a).json()['files']] == ['active.txt']
    assert signed == ['active.txt', 'active.txt'], signed
    assert c.get('/api/v1/files/chunks', headers=a, params={'key':'forgotten.txt'}).status_code == 409
    for expiry in (-1, 0, 3601, True, '20'):
        assert c.post('/api/v1/files/url', headers=a, json={'key':'active.txt','expires_in':expiry}).status_code == 422
    assert c.post('/api/v1/files/url', headers=a, json={'key':'active.txt','expires_in':60}).status_code == 200
    assert c.post('/api/v1/files/upload_url', headers=a, json={'filename':'x.txt'}).status_code == 410
    assert c.get('/api/v1/files', headers=a, params={'prefix':'\u2603'*400}).status_code == 422
    # Complete the old cleanup attempt as a terminal failure, then request a retry.
    jobs.run_once(clock=lambda: jobs.utcnow() + timedelta(seconds=10))
    assert jobs.status(j['job_id']).state == 'failed'
    retried = c.delete('/api/v1/files/x', headers=a)
    assert retried.status_code == 202 and retried.json()['job_id'] != j['job_id']
    storage_service.delete_file = lambda key: False
    assert jobs.run_once().state == 'retrying'
    assert c.delete('/api/v1/files/x', headers=a).json()['cleanup'] == 'pending'
    def acknowledge(key):
        deleted.append(key)
        objects.pop(key, None)
        return True
    storage_service.delete_file = acknowledge
    assert jobs.run_once(clock=lambda: jobs.utcnow() + timedelta(seconds=10)).state == 'completed'
    assert deleted == ['x']
    done = c.post('/api/v1/files/delete', headers=a, json={'key':'x'}).json()
    assert done['cleanup'] == 'completed' and done['job_id'] == retried.json()['job_id']
    public = c.get('/api/v1/jobs/' + done['job_id'], headers=a).json()
    assert public['result'] == {'deleted':True} and 'lease_token' not in public
    # Both queued runs use real file indexing. Older work cannot overwrite accepted rows.
    first_response = c.post('/api/v1/files/reindex', headers=a, json={'key':'active.txt'})
    assert first_response.status_code == 202
    first = first_response.json()
    lease = jobs.claim()
    second = c.post('/api/v1/files/reindex', headers=a, json={'key':'active.txt'}).json()
    assert first['job_id'] != second['job_id']
    objects['active.txt'] = b'new active source'
    try:
        indexing.reindex_storage_file_by_key('active.txt', publication_guard=jobs.JobLease(first['job_id'], lease.lease_token).publication_guard)
    except jobs.PermanentFailure:
        pass
    else:
        raise AssertionError('old publisher was not fenced')
    with Session(engine) as session:
        assert session.exec(select(StorageChunkItem).where(StorageChunkItem.file_key == 'active.txt')).one().content == 'old active source'
    assert jobs.run_once().state == 'completed'
    with Session(engine) as session:
        assert session.exec(select(StorageChunkItem).where(StorageChunkItem.file_key == 'active.txt')).one().content == 'new active source'
"""
    subprocess.run([sys.executable, "-c", script], env=env, check=True, timeout=60)
