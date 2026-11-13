from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from gigamind.security import Actor, require_scope
from gigamind.services.upload_http import recover

router = APIRouter()


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=1024)
    job_id: str = Field(min_length=1, max_length=255)


@router.post(
    "/api/v1/files/upload/recover", dependencies=[Depends(require_scope("admin"))]
)
def recover_upload(request: RecoveryRequest, actor: Actor = Depends(require_scope("admin"))):
    return recover(request.key, request.job_id, actor=actor)
