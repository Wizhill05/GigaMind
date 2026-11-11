"""The default suite must not inherit external service configuration."""

import os
import socket

import pytest


def test_offline_environment_is_isolated():
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    assert os.environ["DATABASE_URL"] == ""
    assert "gigamind-pytest-" in os.environ["DB_PATH"]
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "R2_ENDPOINT_URL", "AWS_ACCESS_KEY_ID"):
        assert name not in os.environ


def test_external_socket_connection_is_blocked():
    with socket.socket() as connection:
        with pytest.raises(RuntimeError, match="External network"):
            connection.connect(("192.0.2.1", 443))
