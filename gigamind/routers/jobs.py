import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, StrictInt
from sqlmodel import Session, select

from gigamind.db.database import engine
from gigamind.db.jobs import Job
from gigamind.security import require_scope
from gigamind.services import jobs

router = APIRouter(
    prefix="/api/v1/jobs", dependencies=[Depends(require_scope("admin"))]
)


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["index_file", "index_conversation"]
    payload: dict
    idempotency_key: str | None = None
    max_attempts: StrictInt = 3


def public(job):
    return {
        "id": job.id,
        "kind": job.kind,
        "payload": json.loads(job.payload_json),
        "idempotency_key": job.idempotency_key,
        "state": job.state,
        "result": json.loads(job.result_json) if job.result_json else None,
        "error": job.error,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "available_at": job.available_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.post("")
def create(req: JobRequest):
    try:
        if req.kind == "index_conversation":
            from gigamind.services.conversation_index import enqueue_conversation

            if set(req.payload) != {"conversation_id"}:
                raise ValueError("index_conversation requires conversation_id")
            return public(enqueue_conversation(
                req.payload["conversation_id"], req.idempotency_key,
                max_attempts=req.max_attempts, engine=engine,
            ))
        return public(
            jobs.enqueue(
                req.kind,
                req.payload,
                req.idempotency_key,
                req.max_attempts,
                engine=engine,
            )
        )
    except jobs.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except LookupError:
        raise HTTPException(404, "Conversation not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("")
def list_jobs(
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000)
):
    with Session(engine) as session:
        rows = session.exec(
            select(Job).order_by(Job.created_at, Job.id).offset(offset).limit(limit)
        ).all()
        return {"jobs": [public(row) for row in rows]}


@router.get("/{job_id}")
def get_job(job_id: str):
    job = jobs.status(job_id, engine=engine)
    if job is None:
        raise HTTPException(404, "Job not found")
    return public(job)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    if not jobs.cancel(job_id, engine=engine):
        if jobs.status(job_id, engine=engine) is None:
            raise HTTPException(404, "Job not found")
        raise HTTPException(409, "Job cannot be cancelled")
    return get_job(job_id)
