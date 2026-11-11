from fastapi import APIRouter, Depends
from pydantic import BaseModel

from gigamind.security import require_scope
from gigamind.services.upload_http import recover

router = APIRouter()


class RecoveryRequest(BaseModel):
    key: str
    job_id: str


@router.post("/api/v1/files/upload/recover", dependencies=[Depends(require_scope("admin"))])
def recover_upload(request: RecoveryRequest):
    return recover(request.key, request.job_id)
