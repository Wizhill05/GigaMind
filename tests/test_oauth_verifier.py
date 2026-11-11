import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from gigamind.services import oauth


@pytest.fixture
def issuer():
    keys = [
        rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2)
    ]
    state = {"keys": [0], "requests": 0, "mode": "ok"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"] += 1
            if state["mode"] == "redirect":
                self.send_response(302)
                self.send_header("Location", "/other")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            if state["mode"] == "large":
                self.wfile.write(b" " * 3000)
                return
            entries = []
            for index in state["keys"]:
                entry = json.loads(
                    jwt.algorithms.RSAAlgorithm.to_jwk(keys[index].public_key())
                )
                entry.update(kid=str(index), use="sig", alg="RS256")
                entries.append(entry)
            self.wfile.write(json.dumps({"keys": entries}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    now = [100.0]
    config = oauth.OAuthConfig(
        "https://issuer/",
        f"http://127.0.0.1:{server.server_port}/keys",
        "client",
        allow_loopback_http=True,
        max_jwks_bytes=1024,
        clock=lambda: now[0],
    )
    oauth._cache.clear()
    yield keys, state, config, now
    server.shutdown()
    server.server_close()
    thread.join()


def token(keys, index=0, **changes):
    claims = {
        "iss": "https://issuer/",
        "aud": "client",
        "sub": "person",
        "exp": int(time.time()) + 300,
        "scope": "read write",
    }
    claims.update(changes)
    return jwt.encode(
        claims, keys[index], algorithm="RS256", headers={"kid": str(index)}
    )


def test_valid_and_cache(issuer):
    keys, state, config, _ = issuer
    identity = oauth.verify_external_token(token(keys), config)
    assert (identity.issuer, identity.subject, identity.scopes) == (
        "https://issuer/",
        "person",
        frozenset({"read", "write"}),
    )
    oauth.verify_external_token(token(keys), config)
    assert state["requests"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": 1},
        {"nbf": int(time.time()) + 300},
        {"iss": "https://issuer"},
        {"aud": "wrong"},
        {"sub": ""},
        {"scope": "x" * 4097},
    ],
)
def test_bad_claims(issuer, changes):
    keys, _, config, _ = issuer
    with pytest.raises(oauth.OAuthTokenError):
        oauth.verify_external_token(token(keys, **changes), config)


def test_forged_and_missing(issuer):
    keys, _, config, _ = issuer
    forged = jwt.encode(
        {
            "iss": config.issuer,
            "aud": config.audience,
            "sub": "p",
            "exp": int(time.time()) + 60,
        },
        keys[1],
        algorithm="RS256",
        headers={"kid": "0"},
    )
    missing = jwt.encode(
        {"iss": config.issuer, "aud": config.audience, "exp": int(time.time()) + 60},
        keys[0],
        algorithm="RS256",
        headers={"kid": "0"},
    )
    for value in (
        forged,
        missing,
        jwt.encode({"sub": "p"}, "s" * 32, algorithm="HS256", headers={"kid": "0"}),
        jwt.encode({"sub": "p"}, key="", algorithm="none", headers={"kid": "0"}),
    ):
        with pytest.raises(oauth.OAuthTokenError):
            oauth.verify_external_token(value, config)


def test_jku_ignored(issuer):
    keys, state, config, _ = issuer
    value = jwt.encode(
        {
            "iss": config.issuer,
            "aud": config.audience,
            "sub": "p",
            "exp": int(time.time()) + 60,
        },
        keys[0],
        algorithm="RS256",
        headers={"kid": "0", "jku": "http://evil.invalid/keys"},
    )
    assert oauth.verify_external_token(value, config).subject == "p"
    assert state["requests"] == 1


def test_rotation_throttled(issuer):
    keys, state, config, now = issuer
    oauth.verify_external_token(token(keys), config)
    state["keys"] = [1]
    for _ in range(2):
        with pytest.raises(oauth.OAuthTokenError):
            oauth.verify_external_token(token(keys, 1), config)
    assert state["requests"] == 1
    now[0] += 31
    assert oauth.verify_external_token(token(keys, 1), config).subject == "person"
    assert state["requests"] == 2


@pytest.mark.parametrize("mode", ["redirect", "large"])
def test_fetch_failures(issuer, mode):
    keys, state, config, _ = issuer
    state["mode"] = mode
    with pytest.raises(oauth.OAuthTokenError):
        oauth.verify_external_token(token(keys), config)
    assert state["requests"] == 1


def test_environment(monkeypatch):
    for name in ("OAUTH_ISSUER", "OAUTH_JWKS_URL", "OAUTH_AUDIENCE"):
        monkeypatch.delenv(name, raising=False)
    assert oauth.verify_external_token("anything") is None
    monkeypatch.setenv("OAUTH_ISSUER", "issuer")
    with pytest.raises(ValueError):
        oauth.load_oauth_config()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/key",
        "https://user:pass@example.com/key",
        "https://example.com/key#frag",
        "http://127.0.0.1/key",
        "file:///tmp/key",
    ],
)
def test_invalid_url(url):
    with pytest.raises(ValueError):
        oauth.OAuthConfig("https://issuer/", url, "audience")


def test_duplicate_kids_and_expired_cache(issuer):
    keys, state, config, now = issuer
    oauth.verify_external_token(token(keys), config)
    state["keys"] = [0, 0]
    now[0] += 301
    with pytest.raises(oauth.OAuthTokenError):
        oauth.verify_external_token(token(keys), config)
    assert state["requests"] == 2
    with pytest.raises(oauth.OAuthTokenError):
        oauth.verify_external_token(token(keys), config)
    assert state["requests"] == 2


@pytest.mark.parametrize(
    "issuer_url",
    [
        "issuer",
        "http://issuer.example/",
        "https://user:pass@issuer.example/",
        "https://issuer.example/#fragment",
        "https://issuer.example/?query=value",
    ],
)
def test_invalid_issuer_urls(issuer_url):
    with pytest.raises(ValueError, match="issuer URL"):
        oauth.OAuthConfig(issuer_url, "https://issuer.example/keys", "audience")


def test_production_rejects_explicit_loopback_http(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="JWKS URL"):
        oauth.OAuthConfig(
            "https://issuer/",
            "http://127.0.0.1/keys",
            "audience",
            allow_loopback_http=True,
        )
