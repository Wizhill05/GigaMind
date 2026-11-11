"""Safe defaults established before test modules import application code."""

import os
import ipaddress
import socket
import tempfile
from pathlib import Path

# Never inherit a developer's database or provider configuration during collection.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["DATABASE_URL"] = ""
_test_dir = tempfile.TemporaryDirectory(prefix="gigamind-pytest-")
os.environ["DB_PATH"] = str(Path(_test_dir.name) / "test.db")
os.environ["GIGAMIND_API_KEY"] = "offline-test-master-key"
os.environ.pop("RENDER", None)
os.environ["ENVIRONMENT"] = "test"
os.environ["EMBEDDING_DIM"] = "768"
for _name in list(os.environ):
    if _name.startswith(
        ("R2_", "GEMINI_", "GOOGLE_API_", "VOYAGE_", "COHERE_", "AWS_", "OAUTH_")
    ):
        os.environ.pop(_name, None)

os.environ.pop("GIGAMIND_PUBLIC_URL", None)
for _name in ("GIGAMIND_STATIC_DIST", "GIGAMIND_DEMO_ENV_DIR", "VITE_SYNTHETIC_DEMO"):
    os.environ.pop(_name, None)
for _name in list(os.environ):
    if _name.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}:
        os.environ.pop(_name, None)

# Native PostgreSQL is opt-in and limited to loopback by its fixture.
if os.environ.get("GIGAMIND_RUN_LOCAL_POSTGRES") != "1":
    os.environ.pop("GIGAMIND_TEST_POSTGRES_URL", None)

_original_getaddrinfo = socket.getaddrinfo
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex


def _loopback_host(host):
    if host is None or host in ("localhost", b"localhost"):
        return True
    try:
        return ipaddress.ip_address(
            host.decode("ascii") if isinstance(host, bytes) else host
        ).is_loopback
    except (ValueError, UnicodeError):
        return False


def _local_address(address):
    return isinstance(address, str) or (
        isinstance(address, tuple) and _loopback_host(address[0])
    )


def _getaddrinfo(host, *args, **kwargs):
    if not _loopback_host(host):
        raise RuntimeError("External DNS resolution is disabled in offline tests")
    return _original_getaddrinfo(host, *args, **kwargs)


def _connect(self, address):
    if not _local_address(address):
        raise RuntimeError("External network access is disabled in offline tests")
    return _original_connect(self, address)


def _connect_ex(self, address):
    if not _local_address(address):
        raise RuntimeError("External network access is disabled in offline tests")
    return _original_connect_ex(self, address)


socket.getaddrinfo = _getaddrinfo
socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
