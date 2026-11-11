"""Server-managed credentials and FastAPI authorization dependencies."""

import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import update, or_
from sqlalchemy import UniqueConstraint
from gigamind.services.oauth import (
    resource_config,
    verify_external_token,
    OAuthTokenError,
)
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlmodel import Field, Session, SQLModel, select
from gigamind.db.database import engine

SCOPES = {
    "memory:read",
    "memory:propose",
    "memory:write",
    "memory:approve",
    "memory:delete",
    "admin",
}


class ClientCredential(SQLModel, table=True):
    __tablename__ = "client_credentials"
    id: str = Field(primary_key=True)
    name: str
    token_hash: str = Field(index=True, unique=True)
    scopes_json: str
    project_ids_json: str
    revoked: bool = False
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    revision: int = 0


class OAuthBinding(SQLModel, table=True):
    __tablename__ = "oauth_bindings"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)
    id: str = Field(primary_key=True)
    issuer: str
    subject: str
    client_id: str = Field(foreign_key="client_credentials.id")
    revoked: bool = False
    created_at: str
    revoked_at: Optional[str] = None


@dataclass
class Actor:
    id: str
    scopes: set[str]
    project_ids: Optional[set[str]]
    is_admin: bool = False


def now_utc():
    return datetime.now(timezone.utc)


def normalize_expiry(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None or parsed <= now_utc():
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("expires_at must be a future timezone-aware ISO timestamp")


def usable(client):
    if client.revoked:
        return False
    try:
        return (
            client.expires_at is None
            or datetime.fromisoformat(client.expires_at) > now_utc()
        )
    except (ValueError, TypeError):
        return False


def client_permissions(client):
    try:
        scopes = json.loads(client.scopes_json)
        projects = json.loads(client.project_ids_json)
    except (TypeError, ValueError):
        raise unauthorized() from None
    if (
        not isinstance(scopes, list)
        or len(scopes) > 100
        or any(not isinstance(scope, str) or scope not in SCOPES for scope in scopes)
        or not isinstance(projects, list)
        or not projects
        or len(projects) > 100
        or any(
            not isinstance(project, str) or not project.strip() or len(project) > 200
            for project in projects
        )
    ):
        raise unauthorized()
    return set(scopes) - {"admin"}, {project.strip() for project in projects}


def record_use(session, client):
    now = now_utc()
    cutoff_time = now - timedelta(minutes=5)
    try:
        if (
            client.last_used_at is not None
            and datetime.fromisoformat(client.last_used_at) >= cutoff_time
        ):
            return
    except (ValueError, TypeError):
        pass
    cutoff = cutoff_time.isoformat()
    session.exec(
        update(ClientCredential)
        .where(
            ClientCredential.id == client.id,
            or_(
                ClientCredential.last_used_at == None,
                ClientCredential.last_used_at < cutoff,
            ),
        )
        .values(last_used_at=now.isoformat())
    )
    session.commit()


def get_actor(authorization: Optional[str] = Header(default=None)) -> Actor:
    if not authorization or not authorization.startswith("Bearer "):
        raise unauthorized()
    token = authorization[7:].strip()
    if not token or len(token) > 16384:
        raise unauthorized()
    master = os.getenv("GIGAMIND_API_KEY", "")
    if (
        master
        and master != "gigamind-secret-key-change-me"
        and hmac.compare_digest(token.encode(), master.encode())
    ):
        return Actor("master", set(SCOPES), None, True)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with Session(engine) as session:
        client = session.exec(
            select(ClientCredential).where(ClientCredential.token_hash == digest)
        ).first()
        if client and usable(client):
            scopes, projects = client_permissions(client)
            record_use(session, client)
            return Actor(
                client.id,
                scopes,
                projects,
            )
    config = resource_config()
    if config:
        try:
            identity = verify_external_token(token, config[0])
            with Session(engine) as session:
                binding = session.exec(
                    select(OAuthBinding).where(
                        OAuthBinding.issuer == identity.issuer,
                        OAuthBinding.subject == identity.subject,
                        OAuthBinding.revoked == False,
                    )
                ).first()
                client = (
                    session.get(ClientCredential, binding.client_id)
                    if binding
                    else None
                )
                if client and usable(client):
                    scopes, projects = client_permissions(client)
                    record_use(session, client)
                    return Actor(
                        client.id,
                        scopes & identity.scopes,
                        projects,
                        False,
                    )
        except OAuthTokenError:
            pass
    raise unauthorized()


def unauthorized():
    config = resource_config()
    headers = (
        {
            "WWW-Authenticate": f'Bearer resource_metadata="{config[1]}/.well-known/oauth-protected-resource/mcp"'
        }
        if config
        else None
    )
    return HTTPException(401, "Missing or invalid Bearer credential", headers=headers)


def require_scope(*scopes: str):
    def dependency(actor: Actor = Depends(get_actor)) -> Actor:
        if not actor.is_admin and (
            "admin" in scopes or not set(scopes).issubset(actor.scopes)
        ):
            raise HTTPException(403, "Insufficient scope")
        return actor

    return dependency


def create_client(
    name: str,
    scopes: list[str],
    project_ids: list[str],
    expires_at: Optional[str] = None,
):
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise ValueError("Client name must contain 1 to 200 characters")
    if (
        not isinstance(scopes, list)
        or len(scopes) > 100
        or any(not isinstance(scope, str) or scope not in SCOPES for scope in scopes)
    ):
        raise ValueError("Valid client scopes are required")
    if (
        not isinstance(project_ids, list)
        or not project_ids
        or len(project_ids) > 100
        or any(
            not isinstance(project, str) or not project.strip() or len(project) > 200
            for project in project_ids
        )
    ):
        raise ValueError("Valid project IDs are required")
    project_ids = list(dict.fromkeys(project.strip() for project in project_ids))
    expires_at = normalize_expiry(expires_at)
    token = "gm_" + secrets.token_urlsafe(32)
    client = ClientCredential(
        id=str(uuid.uuid4()),
        name=name.strip(),
        created_at=now_utc().isoformat(),
        expires_at=expires_at,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        scopes_json=json.dumps(scopes),
        project_ids_json=json.dumps(project_ids),
    )
    with Session(engine, expire_on_commit=False) as session:
        session.add(client)
        session.commit()
    return client, token


def public_client(client: ClientCredential):
    return {
        "id": client.id,
        "name": client.name,
        "scopes": json.loads(client.scopes_json),
        "project_ids": json.loads(client.project_ids_json),
        "revoked": client.revoked,
        "created_at": client.created_at,
        "expires_at": client.expires_at,
        "last_used_at": client.last_used_at,
        "revision": client.revision,
    }
