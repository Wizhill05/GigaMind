from test_oauth_verifier import issuer
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import SQLModel


def test_lifecycle(monkeypatch, tmp_path):
    from gigamind import main, security
    engine = create_engine(f"sqlite:///{tmp_path / 'clients.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(security, "engine", engine)
    monkeypatch.setenv("GIGAMIND_API_KEY", "test-master-secret")
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(security, "now_utc", lambda: now)
    monkeypatch.setattr(main, "now_utc", lambda: now)
    headers = {"Authorization": "Bearer test-master-secret"}
    body = {"name": "app", "scopes": ["memory:read"], "project_ids": ["p"]}
    client = TestClient(main.app)
    for expiry in ("bad", "2029-01-01T00:00:00+00:00", "2031-01-01T00:00:00"):
        assert client.post('/api/v1/admin/clients', headers=headers, json={**body, "expires_at": expiry}).status_code == 422
    body["expires_at"] = (now + timedelta(hours=1)).isoformat()
    created = client.post('/api/v1/admin/clients', headers=headers, json=body).json()
    token = created['token']
    ident = created['client']['id']
    assert security.get_actor('Bearer ' + token).id == ident
    listed = client.get('/api/v1/admin/clients', headers=headers).json()['clients'][0]
    assert listed['last_used_at'] and 'token_hash' not in listed
    with engine.connect() as conn:
        assert token not in str(conn.execute(text('SELECT * FROM client_credentials')).all())
    path = f'/api/v1/admin/clients/{ident}/rotate'
    rotated = client.post(path, headers=headers, json={'expected_revision': 0})
    assert rotated.status_code == 200
    assert client.post(path, headers=headers, json={'expected_revision': 0}).status_code == 409
    with pytest.raises(Exception):
        security.get_actor('Bearer ' + token)
    assert security.get_actor('Bearer ' + rotated.json()['token']).id == ident
    monkeypatch.setattr(security, 'now_utc', lambda: now + timedelta(hours=2))
    monkeypatch.setattr(main, 'now_utc', lambda: now + timedelta(hours=2))
    with pytest.raises(Exception):
        security.get_actor('Bearer ' + rotated.json()['token'])
    assert client.post(path, headers=headers, json={'expected_revision': 1}).status_code == 409
    assert client.post(f'/api/v1/admin/clients/{ident}/revoke', headers=headers).status_code == 200
    assert client.post(f'/api/v1/admin/clients/{ident}/revoke', headers=headers).status_code == 200


def test_legacy_client_migration(tmp_path):
    from gigamind.db import migrations
    from gigamind import security  # register credentials
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    migrations.migrate(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql('DROP TABLE client_credentials')
        conn.exec_driver_sql('CREATE TABLE client_credentials (id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL, scopes_json TEXT NOT NULL, project_ids_json TEXT NOT NULL, revoked BOOLEAN NOT NULL)')
        conn.exec_driver_sql("INSERT INTO client_credentials VALUES ('id','old','hash','[]','[]',0)")
        conn.exec_driver_sql('DELETE FROM schema_migrations')
        conn.exec_driver_sql('INSERT INTO schema_migrations VALUES (1)')
    migrations.migrate(engine)
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT token_hash, created_at, expires_at, last_used_at, revision FROM client_credentials').one() == ('hash', None, None, None, 0)


def test_expired_external_binding(issuer, monkeypatch, tmp_path):
    import time
    import jwt
    from fastapi import HTTPException
    from sqlmodel import Session
    from gigamind import security
    keys, _, config, _ = issuer
    for key, value in {
        'OAUTH_ISSUER': config.issuer, 'OAUTH_JWKS_URL': config.jwks_url,
        'OAUTH_AUDIENCE': 'https://resource.example/mcp',
        'GIGAMIND_PUBLIC_URL': 'https://resource.example', 'OAUTH_ALLOW_LOOPBACK_HTTP': 'true',
    }.items():
        monkeypatch.setenv(key, value)
    engine = create_engine(f"sqlite:///{tmp_path / 'oauth.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(security, 'engine', engine)
    credential, _ = security.create_client('app', ['memory:read'], ['p'])
    client_id = credential.id
    with Session(engine) as session:
        credential = session.get(security.ClientCredential, credential.id)
        session.add(credential)
        session.add(security.OAuthBinding(id='binding', issuer=config.issuer, subject='person', client_id=credential.id, created_at='now'))
        session.commit()
    token = jwt.encode({'iss': config.issuer, 'sub': 'person', 'aud': 'https://resource.example/mcp', 'exp': int(time.time()) + 300, 'scope': 'memory:read'}, keys[0], algorithm='RS256', headers={'kid': '0'})
    assert security.get_actor('Bearer ' + token).id == client_id
    with Session(engine) as session:
        stored = session.get(security.ClientCredential, client_id)
        stored.expires_at = '2000-01-01T00:00:00+00:00'
        session.add(stored)
        session.commit()
    with pytest.raises(HTTPException) as exc:
        security.get_actor('Bearer ' + token)
    assert exc.value.status_code == 401


def test_concurrent_rotation(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from gigamind import main, security
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={'check_same_thread': False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, 'engine', engine)
    monkeypatch.setattr(security, 'engine', engine)
    monkeypatch.setenv('GIGAMIND_API_KEY', 'test-master-secret')
    client = TestClient(main.app)
    headers = {'Authorization': 'Bearer test-master-secret'}
    created = client.post('/api/v1/admin/clients', headers=headers, json={'name': 'race', 'scopes': [], 'project_ids': ['p']}).json()
    path = '/api/v1/admin/clients/' + created['client']['id'] + '/rotate'
    def rotate(_):
        return client.post(path, headers=headers, json={'expected_revision': 0})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(rotate, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r.json()['token'] for r in responses if r.status_code == 200)
    assert security.get_actor('Bearer ' + winner).id == created['client']['id']
    client.post('/api/v1/admin/clients/' + created['client']['id'] + '/revoke', headers=headers)
    assert client.post(path, headers=headers, json={'expected_revision': 1}).status_code == 409
