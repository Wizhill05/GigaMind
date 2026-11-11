from typing import Optional, Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from gigamind.security import Actor, get_actor
from gigamind.services import trust

router = APIRouter(prefix="/api/v1/review", tags=["review"])

from gigamind.services.trust_schema import Proposal, Resolution, Restore


def dump(obj):
    return obj.model_dump() if hasattr(obj, "model_dump") else obj.dict()


@router.post("/proposals")
def create(body: Proposal, actor: Actor = Depends(get_actor)):
    return trust.create_proposal(actor, **dump(body))


@router.get("/proposals")
def proposals(
    project_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    actor: Actor = Depends(get_actor),
):
    """List visible proposals; limit (1–100) and offset are optional."""
    return trust.list_proposals(actor, project_id, limit=limit, offset=offset)


@router.post("/proposals/{proposal_id}/resolve")
def resolve(proposal_id: str, body: Resolution, actor: Actor = Depends(get_actor)):
    return trust.resolve_proposal(actor, proposal_id, **dump(body))


@router.get("/memories/{memory_id}/history")
def history(memory_id: str, actor: Actor = Depends(get_actor)):
    return trust.get_history(actor, memory_id)


@router.get("/memories/{memory_id}")
def memory(memory_id: str, actor: Actor = Depends(get_actor)):
    return trust.get_memory(actor, memory_id)


@router.post("/memories/{memory_id}/restore")
def restore(memory_id: str, body: Restore, actor: Actor = Depends(get_actor)):
    return trust.restore_memory(actor, memory_id, **dump(body))


@router.get("/activity")
def activity(
    project_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    actor: Actor = Depends(get_actor),
):
    """List visible activity; limit (1–100) and offset are optional."""
    return trust.list_activity(actor, project_id, limit=limit, offset=offset)
