from typing import Optional, Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StrictInt, ConfigDict
from gigamind.security import Actor, get_actor
from gigamind.services import trust, context, knowledge_validity
from gigamind.services import knowledge_list

router = APIRouter(prefix="/api/v1/review", tags=["review"])


@router.get("/knowledge")
def knowledge(
    q: Optional[str] = None,
    project_id: Optional[str] = None,
    status: str = "accepted",
    limit: int = 20,
    offset: int = 0,
    actor: Actor = Depends(get_actor),
):
    return knowledge_list.list_knowledge(actor, q, project_id, status, limit, offset)


from gigamind.services.trust_schema import (
    Proposal,
    Resolution,
    Restore,
    ApprovalPreview,
)


def dump(obj):
    return obj.model_dump() if hasattr(obj, "model_dump") else obj.dict()


class DeleteMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=1)


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


class InspectEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=1)


@router.post("/proposals/{proposal_id}/inspect-evidence")
def inspect_evidence(
    proposal_id: str, body: InspectEvidence, actor: Actor = Depends(get_actor)
):
    from gigamind.services import evidence_inspection

    return evidence_inspection.inspect(actor, proposal_id, body.expected_revision)


@router.post("/proposals/{proposal_id}/resolve")
def resolve(proposal_id: str, body: Resolution, actor: Actor = Depends(get_actor)):
    return trust.resolve_proposal(actor, proposal_id, **dump(body))


@router.post("/proposals/{proposal_id}/preview")
def preview(proposal_id: str, body: ApprovalPreview, actor: Actor = Depends(get_actor)):
    return trust.preview_proposal(actor, proposal_id, **dump(body))


@router.get("/memories/{memory_id}/history")
def history(memory_id: str, actor: Actor = Depends(get_actor)):
    return trust.get_history(actor, memory_id)


@router.get("/memories/{memory_id}")
def memory(memory_id: str, actor: Actor = Depends(get_actor)):
    return trust.get_memory(actor, memory_id)


@router.post("/memories/{memory_id}/restore")
def restore(memory_id: str, body: Restore, actor: Actor = Depends(get_actor)):
    return trust.restore_memory(actor, memory_id, **dump(body))


class Validity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=1)
    valid_from: Optional[str]
    valid_until: Optional[str]


@router.post("/memories/{memory_id}/validity")
def validity(memory_id: str, body: Validity, actor: Actor = Depends(get_actor)):
    return knowledge_validity.set_validity(actor, memory_id, **dump(body))


@router.post("/memories/{memory_id}/delete")
def delete(memory_id: str, body: DeleteMemory, actor: Actor = Depends(get_actor)):
    return trust.delete_memory(actor, memory_id, **dump(body))


@router.get("/activity")
def activity(
    project_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    actor: Actor = Depends(get_actor),
):
    """List visible activity; limit (1–100) and offset are optional."""
    return trust.list_activity(actor, project_id, limit=limit, offset=offset)


@router.get("/search")
def search(
    query: str,
    project_id: Optional[str] = None,
    limit: int = 5,
    actor: Actor = Depends(get_actor),
):
    return {"results": context.search_accepted(actor, query, project_id, limit)}


@router.get("/context")
def get_context(
    query: str,
    project_id: Optional[str] = None,
    token_budget: int = 4096,
    actor: Actor = Depends(get_actor),
):
    return context.get_context(actor, query, project_id, token_budget)


from gigamind.services import coordination
from gigamind.services.coordination_schema import (
    HandoffInput,
    IssueInput,
    IssueResolution,
)


@router.post("/handoffs")
def save_handoff(body: HandoffInput, actor: Actor = Depends(get_actor)):
    return coordination.save_handoff(actor, **dump(body))


@router.get("/handoffs/latest")
def latest_handoff(project_id: Optional[str] = None, actor: Actor = Depends(get_actor)):
    return coordination.latest_handoff(actor, project_id)


@router.get("/handoffs")
def handoffs(
    project_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    actor: Actor = Depends(get_actor),
):
    return coordination.list_handoffs(actor, project_id, limit, offset)


@router.post("/issues")
def report_issue(body: IssueInput, actor: Actor = Depends(get_actor)):
    return coordination.report_memory_issue(actor, **dump(body))


@router.get("/issues")
def issues(
    project_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    actor: Actor = Depends(get_actor),
):
    return coordination.list_issues(actor, project_id, limit, offset)


@router.post("/issues/{issue_id}/resolve")
def resolve_issue(
    issue_id: str, body: IssueResolution, actor: Actor = Depends(get_actor)
):
    return coordination.resolve_issue(actor, issue_id, **dump(body))
