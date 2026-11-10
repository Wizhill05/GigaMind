from typing import Optional, Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from gigamind.security import Actor, get_actor
from gigamind.services import trust

router = APIRouter(prefix='/api/v1/review', tags=['review'])

class Evidence(BaseModel):
    source_type: str = Field(min_length=1, max_length=100)
    source_id: str = Field(min_length=1, max_length=512)
    quote: str = Field(min_length=1, max_length=10000)
    source_role: Optional[str] = Field(default=None, max_length=100)
class Proposal(BaseModel):
    content: str = Field(min_length=1, max_length=50000)
    category: str = Field(default='general', min_length=1, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=100)
    project_id: Optional[str] = Field(default=None, max_length=200)
    evidence: list[Evidence] = Field(max_length=100)
    kind: Literal['fact', 'preference', 'decision'] = 'fact'
    subject: Optional[str] = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)
class Resolution(BaseModel):
    action: Literal['approve', 'reject']
    expected_revision: int = Field(ge=1)
    content: Optional[str] = Field(default=None, min_length=1, max_length=50000)
    supersedes: list[str] = Field(default_factory=list, max_length=100)
class Restore(BaseModel):
    revision: int = Field(ge=1)
    expected_revision: int = Field(ge=1)

def dump(obj): return obj.model_dump() if hasattr(obj, 'model_dump') else obj.dict()
@router.post('/proposals')
def create(body: Proposal, actor: Actor = Depends(get_actor)):
    return trust.create_proposal(actor, **dump(body))
@router.get('/proposals')
def proposals(project_id: Optional[str] = None, actor: Actor = Depends(get_actor)):
    return trust.list_proposals(actor, project_id)
@router.post('/proposals/{proposal_id}/resolve')
def resolve(proposal_id: str, body: Resolution, actor: Actor = Depends(get_actor)):
    return trust.resolve_proposal(actor, proposal_id, **dump(body))
@router.get('/memories/{memory_id}/history')
def history(memory_id: str, actor: Actor = Depends(get_actor)):
    return trust.get_history(actor, memory_id)
@router.post('/memories/{memory_id}/restore')
def restore(memory_id: str, body: Restore, actor: Actor = Depends(get_actor)):
    return trust.restore_memory(actor, memory_id, **dump(body))
@router.get('/activity')
def activity(project_id: Optional[str] = None, actor: Actor = Depends(get_actor)):
    return trust.list_activity(actor, project_id)
