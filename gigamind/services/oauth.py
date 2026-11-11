"""Verify external RS256 bearer tokens against a configured JWKS.

Set OAUTH_ISSUER, OAUTH_JWKS_URL and OAUTH_AUDIENCE together. An unset
configuration disables verification. Integrators must map VerifiedIdentity to
local authorization separately; this module does not issue credentials.
"""

import ipaddress
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

import jwt


class OAuthTokenError(ValueError):
    """A token or its configured signing keys could not be verified."""


@dataclass(frozen=True)
class OAuthConfig:
    issuer: str
    jwks_url: str
    audience: str
    cache_ttl: float = 300
    refresh_interval: float = 30
    timeout: float = 5
    max_jwks_bytes: int = 262144
    allow_loopback_http: bool = False
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)

    def __post_init__(self):
        if not all(
            isinstance(x, str) and x.strip() and x == x.strip()
            for x in (self.issuer, self.jwks_url, self.audience)
        ):
            raise ValueError("OAuth issuer, JWKS URL and audience are required")
        production = os.getenv("ENVIRONMENT", "development").strip().lower() in (
            "prod",
            "production",
        ) or bool(os.getenv("RENDER"))
        for label, endpoint in (("issuer", self.issuer), ("JWKS", self.jwks_url)):
            try:
                url = urlsplit(endpoint)
                host = url.hostname
                _ = url.port
                loopback = host == "localhost" or (
                    host is not None and _is_loopback(host)
                )
                permitted_http = (
                    self.allow_loopback_http and loopback and not production
                )
                if (
                    not host
                    or url.username is not None
                    or url.password is not None
                    or "#" in endpoint
                    or (label == "issuer" and url.query)
                    or not (
                        url.scheme == "https"
                        or (url.scheme == "http" and permitted_http)
                    )
                ):
                    raise ValueError
            except ValueError:
                raise ValueError(f"Invalid OAuth {label} URL") from None
        if not (
            1 <= self.cache_ttl <= 86400
            and 1 <= self.refresh_interval <= 3600
            and 0 < self.timeout <= 30
            and 1024 <= self.max_jwks_bytes <= 1048576
        ):
            raise ValueError("Invalid OAuth cache or fetch limits")


def _is_loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def load_oauth_config():
    values = [
        os.getenv(name, "")
        for name in ("OAUTH_ISSUER", "OAUTH_JWKS_URL", "OAUTH_AUDIENCE")
    ]
    if not any(values):
        return None
    return OAuthConfig(*values)


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    scopes: frozenset[str]
    expires_at: int


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_lock = threading.Lock()
_cache = {}  # config -> (keys, fetched_at, last_refresh_attempt)
_MAX_CACHE = 64


def _fetch(config):
    try:
        with build_opener(_NoRedirect()).open(
            config.jwks_url, timeout=config.timeout
        ) as response:
            data = response.read(config.max_jwks_bytes + 1)
        if len(data) > config.max_jwks_bytes:
            raise ValueError
        document = json.loads(data)
        entries = document["keys"]
        if not isinstance(entries, list) or len(entries) > 100:
            raise ValueError
        keys = {}
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError
            kid = entry.get("kid")
            if not isinstance(kid, str) or not kid or len(kid) > 256:
                continue
            if kid in seen:
                raise ValueError
            seen.add(kid)
            if (
                entry.get("kty") != "RSA"
                or entry.get("use", "sig") != "sig"
                or entry.get("alg", "RS256") != "RS256"
                or (
                    "key_ops" in entry
                    and (
                        not isinstance(entry["key_ops"], list)
                        or "verify" not in entry["key_ops"]
                    )
                )
            ):
                continue
            key = jwt.PyJWK.from_dict(entry, algorithm="RS256").key
            if key.key_size < 2048:
                continue
            keys[kid] = key
        return keys
    except Exception:
        raise OAuthTokenError("Unable to retrieve valid signing keys") from None


def _key(config, kid):
    # Serialize fetches as well as cache updates to prevent concurrent refresh storms.
    with _lock:
        now = config.clock()
        entry = _cache.get(config)
        if entry:
            keys, fetched, attempted = entry
            if now - fetched < config.cache_ttl and kid in keys:
                return keys[kid]
            if now - attempted < config.refresh_interval:
                raise OAuthTokenError("Signing key unavailable")
        else:
            keys, fetched = {}, float("-inf")
        if len(_cache) >= _MAX_CACHE and config not in _cache:
            _cache.pop(next(iter(_cache)))
        _cache[config] = (keys, fetched, now)
        keys = _fetch(config)
        _cache[config] = (keys, now, now)
        if kid not in keys:
            raise OAuthTokenError("Signing key unavailable")
        return keys[kid]


def verify_external_token(token, config=None):
    """Return a verified identity, None if disabled, or raise OAuthTokenError.

    Pass an OAuthConfig explicitly or load it from the three environment values.
    The caller is responsible for local identity binding and authorization.
    """
    if config is None:
        config = load_oauth_config()
    if config is None:
        return None
    if not isinstance(token, str) or len(token) > 16384 or not token:
        raise OAuthTokenError("Invalid token")
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if (
            header.get("alg") != "RS256"
            or not isinstance(kid, str)
            or not kid
            or len(kid) > 256
        ):
            raise ValueError
        claims = jwt.decode(
            token,
            _key(config, kid),
            algorithms=["RS256"],
            issuer=config.issuer,
            audience=config.audience,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
        subject = claims["sub"]
        scope = claims.get("scope", "")
        exp = claims["exp"]
        if (
            not isinstance(subject, str)
            or not subject
            or len(subject) > 1024
            or not isinstance(scope, str)
            or len(scope) > 4096
            or isinstance(exp, bool)
            or not isinstance(exp, int)
        ):
            raise ValueError
        scopes = scope.split()
        if len(scopes) > 100 or any(len(s) > 256 for s in scopes):
            raise ValueError
        return VerifiedIdentity(config.issuer, subject, frozenset(scopes), exp)
    except OAuthTokenError:
        raise
    except Exception:
        raise OAuthTokenError("Invalid token") from None
