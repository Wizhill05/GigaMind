import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from gigamind.db.database import engine
from gigamind.security import Actor, ClientCredential, OAuthBinding, require_scope
from gigamind.services.oauth import resource_config

router = APIRouter()


class BindingRequest(BaseModel):
    issuer: str = Field(min_length=1, max_length=2048)
    subject: str = Field(min_length=1, max_length=1024)
    client_id: str


@router.get('/.well-known/oauth-protected-resource')
@router.get('/.well-known/oauth-protected-resource/mcp')
def discovery():
    config = resource_config()
    if not config:
        raise HTTPException(404, 'OAuth is not configured')
    return {'resource': config[0].audience, 'authorization_servers': [config[0].issuer], 'bearer_methods_supported': ['header']}


@router.get('/api/v1/admin/oauth/bindings')
def list_bindings(actor: Actor = Depends(require_scope('admin'))):
    with Session(engine) as session:
        return {'bindings': session.exec(select(OAuthBinding)).all()}


@router.post('/api/v1/admin/oauth/bindings', status_code=201)
def add_binding(req: BindingRequest, actor: Actor = Depends(require_scope('admin'))):
    config = resource_config()
    if not config or req.issuer != config[0].issuer:
        raise HTTPException(422, 'Issuer must match configured issuer')
    with Session(engine) as session:
        client = session.get(ClientCredential, req.client_id)
        if not client or client.revoked:
            raise HTTPException(422, 'Active client required')
        binding = OAuthBinding(id=str(uuid.uuid4()), issuer=req.issuer, subject=req.subject, client_id=req.client_id, created_at=datetime.now(timezone.utc).isoformat())
        session.add(binding)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, 'Binding already exists') from None
        session.refresh(binding)
        return binding


@router.post('/api/v1/admin/oauth/bindings/{binding_id}/revoke')
def revoke_binding(binding_id: str, actor: Actor = Depends(require_scope('admin'))):
    with Session(engine) as session:
        binding = session.get(OAuthBinding, binding_id)
        if not binding:
            raise HTTPException(404, 'Binding not found')
        if not binding.revoked:
            binding.revoked = True
            binding.revoked_at = datetime.now(timezone.utc).isoformat()
            session.add(binding)
            session.commit()
            session.refresh(binding)
        return binding
