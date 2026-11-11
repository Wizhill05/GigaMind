import os
import time

import jwt
from fastapi.testclient import TestClient
from test_oauth_verifier import issuer


def test_external_binding_and_discovery(issuer, monkeypatch):
    keys, _, config, _ = issuer
    monkeypatch.setenv('OAUTH_ISSUER', config.issuer)
    monkeypatch.setenv('OAUTH_JWKS_URL', config.jwks_url)
    monkeypatch.setenv('OAUTH_AUDIENCE', 'https://resource.example/mcp')
    monkeypatch.setenv('GIGAMIND_PUBLIC_URL', 'https://resource.example')
    monkeypatch.setenv('OAUTH_ALLOW_LOOPBACK_HTTP', 'true')
    monkeypatch.setenv('GIGAMIND_API_KEY', 'test-master-secret')
    from gigamind.main import app
    from gigamind.security import get_actor, require_scope
    from fastapi import HTTPException
    import pytest

    def signed(**changes):
        claims = {'iss': config.issuer, 'sub': 'person', 'aud': 'https://resource.example/mcp', 'exp': int(time.time()) + 300, 'scope': 'memory:read memory:write admin'}
        claims.update(changes)
        return jwt.encode(claims, keys[0], algorithm='RS256', headers={'kid': '0'})

    with TestClient(app) as client:
        master = {'Authorization': 'Bearer test-master-secret'}
        created = client.post('/api/v1/admin/clients', headers=master, json={'name': 'test', 'scopes': ['memory:read'], 'project_ids': ['projectA']}).json()
        local = created['token']
        assert get_actor('Bearer ' + local).scopes == {'memory:read'}
        bearer = 'Bearer ' + signed()
        with pytest.raises(HTTPException):
            get_actor(bearer)
        binding = client.post('/api/v1/admin/oauth/bindings', headers=master, json={'issuer': config.issuer, 'subject': 'person', 'client_id': created['client']['id']})
        assert binding.status_code == 201
        actor = get_actor(bearer)
        assert actor.scopes == {'memory:read'} and actor.project_ids == {'projectA'} and not actor.is_admin
        with pytest.raises(HTTPException):
            require_scope('admin')(actor)
        for bad in [signed(aud='wrong'), signed(sub='other'), signed()[:-3] + 'xyz']:
            with pytest.raises(HTTPException):
                get_actor('Bearer ' + bad)
        metadata = client.get('/.well-known/oauth-protected-resource/mcp', headers={'Host': 'evil.example'}).json()
        assert metadata['resource'] == 'https://resource.example/mcp'
        response = client.post('/mcp', headers={'Host': 'evil.example'})
        assert response.status_code == 401
        assert 'https://resource.example/.well-known/oauth-protected-resource/mcp' in response.headers['www-authenticate']
        assert client.post('/api/v1/admin/oauth/bindings', headers=master, json={'issuer': config.issuer, 'subject': 'person', 'client_id': created['client']['id']}).status_code == 409
        assert client.post('/api/v1/admin/oauth/bindings/' + binding.json()['id'] + '/revoke', headers=master).status_code == 200
        with pytest.raises(HTTPException):
            get_actor(bearer)

        second = client.post('/api/v1/admin/oauth/bindings', headers=master, json={'issuer': config.issuer, 'subject': 'second', 'client_id': created['client']['id']})
        assert second.status_code == 201
        second_bearer = 'Bearer ' + signed(sub='second')
        assert get_actor(second_bearer).id == created['client']['id']
        assert client.post('/api/v1/admin/clients/' + created['client']['id'] + '/revoke', headers=master).status_code == 200
        with pytest.raises(HTTPException):
            get_actor(second_bearer)
        with pytest.raises(HTTPException):
            get_actor('Bearer ' + local)
