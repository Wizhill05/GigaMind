"""Server-managed credentials and FastAPI authorization dependencies."""
import hashlib
import hmac
import json
import os
import secrets
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlmodel import Field, Session, SQLModel, select
from gigamind.db.database import engine

SCOPES = {"memory:read", "memory:propose", "memory:write", "memory:approve", "memory:delete", "admin"}

class ClientCredential(SQLModel, table=True):
    __tablename__ = "client_credentials"
    id: str = Field(primary_key=True)
    name: str
    token_hash: str = Field(index=True, unique=True)
    scopes_json: str
    project_ids_json: str
    revoked: bool = False

@dataclass
class Actor:
    id: str
    scopes: set[str]
    project_ids: Optional[set[str]]
    is_admin: bool = False


def get_actor(authorization: Optional[str] = Header(default=None)) -> Actor:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Bearer credential")
    token = authorization[7:].strip()
    master = os.getenv("GIGAMIND_API_KEY", "")
    if master and master != "gigamind-secret-key-change-me" and hmac.compare_digest(token, master):
        return Actor("master", set(SCOPES), None, True)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with Session(engine) as session:
        client = session.exec(select(ClientCredential).where(ClientCredential.token_hash == digest)).first()
        if client and not client.revoked:
            projects = json.loads(client.project_ids_json)
            return Actor(client.id, set(json.loads(client.scopes_json)), set(projects) if projects is not None else None)
    raise HTTPException(401, "Missing or invalid Bearer credential")


def require_scope(*scopes: str):
    def dependency(actor: Actor = Depends(get_actor)) -> Actor:
        if not actor.is_admin and not set(scopes).issubset(actor.scopes):
            raise HTTPException(403, "Insufficient scope")
        return actor
    return dependency


def create_client(name: str, scopes: list[str], project_ids: list[str]):
    token = "gm_" + secrets.token_urlsafe(32)
    client = ClientCredential(id=str(uuid.uuid4()), name=name, token_hash=hashlib.sha256(token.encode()).hexdigest(), scopes_json=json.dumps(scopes), project_ids_json=json.dumps(project_ids))
    with Session(engine) as session:
        session.add(client)
        session.commit()
        session.refresh(client)
    return client, token


def public_client(client: ClientCredential):
    return {"id": client.id, "name": client.name, "scopes": json.loads(client.scopes_json), "project_ids": json.loads(client.project_ids_json), "revoked": client.revoked}
