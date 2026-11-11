"""Durable, reference-aware file cleanup."""

import json
import uuid
from contextlib import contextmanager
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import delete, update
from sqlmodel import Session, select

from gigamind.db.database import MemoryItem, StorageChunkItem, StorageFileItem
from gigamind.db.jobs import Job, ResourceJobState, UploadManifest
from gigamind.security import Actor
from gigamind.services import jobs


def owned_key(key):
    if not isinstance(key, str) or not key or key.startswith("//"):
        return False
    try:
        return not urlsplit(key).scheme
    except ValueError:
        return False


def validate_key(key):
    try:
        jobs.validate_resource_key(key)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not owned_key(key) or any(ord(char) < 32 or ord(char) == 127 for char in key):
        raise HTTPException(422, "Invalid file key")


def tombstoned_keys(keys, engine=None):
    keys = list(set(keys))
    if not keys:
        return set()
    with Session(jobs.resolve_engine(engine)) as session:
        return set(
            session.exec(
                select(ResourceJobState.key).where(
                    ResourceJobState.key.in_(keys), ResourceJobState.deleted.is_(True)
                )
            ).all()
        )


def require_active(key, engine=None):
    validate_key(key)
    if key in tombstoned_keys([key], engine):
        raise HTTPException(409, "File has been deleted")


@contextmanager
def active_access(key, engine=None):
    """Order an access admission against forgetting the same resource."""
    validate_key(key)
    with Session(jobs.resolve_engine(engine)) as session:
        owner = jobs.lock_resource(session, key, jobs.stamp(jobs.utcnow()))
        if owner.deleted:
            raise HTTPException(409, "File has been deleted")
        yield
        session.commit()


def download_url(key, *, engine=None, **options):
    from gigamind.services.storage import storage_service

    with active_access(key, engine):
        return storage_service.get_presigned_download_url(key=key, **options)


def referenced(session, key):
    query = select(MemoryItem.media_url, MemoryItem.attachments_json).execution_options(
        yield_per=20
    )
    for item in session.exec(query):
        if item.media_url == key:
            return True
        try:
            attachments = json.loads(item.attachments_json or "[]")
        except (TypeError, ValueError):
            return True
        if not isinstance(attachments, list):
            return True
        for attachment in attachments:
            if not isinstance(attachment, dict):
                return True
            if attachment.get("key") == key:
                return True
    return False


def request_delete(actor, key, engine=None):
    if not isinstance(actor, Actor) or actor.is_admin is not True:
        raise HTTPException(403, "Admin required")
    validate_key(key)
    now = jobs.stamp(jobs.utcnow())
    with Session(jobs.resolve_engine(engine), expire_on_commit=False) as session:
        owner = jobs.lock_resource(session, key, now)
        manifest = session.get(UploadManifest, key)
        if manifest and manifest.state in {"inflight", "unknown"}:
            raise HTTPException(409, "Upload outcome is unresolved")
        if referenced(session, key):
            raise HTTPException(
                409, "File is referenced or attachment metadata cannot be verified"
            )
        current = (
            session.get(Job, owner.current_job_id) if owner.current_job_id else None
        )
        if (
            owner.deleted
            and current
            and current.kind == "delete_file"
            and current.state in ("queued", "running", "retrying", "completed")
        ):
            session.commit()
            return current
        jobs.cancel_active(session, key, now)
        session.exec(delete(StorageChunkItem).where(StorageChunkItem.file_key == key))
        session.exec(delete(StorageFileItem).where(StorageFileItem.key == key))
        job = Job(
            id=uuid.uuid4().hex,
            kind="delete_file",
            resource_key=key,
            payload_json=json.dumps({"key": key}),
            state="queued",
            max_attempts=3,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        owner.deleted = True
        owner.current_job_id = job.id
        owner.updated_at = now
        session.add(job)
        session.commit()
        return job


def cleanup_file(key, lease):
    from gigamind.services.storage import storage_service

    with Session(jobs.resolve_engine(lease.engine)) as session:
        now = jobs.stamp(lease.clock())
        owner = jobs.lock_resource(session, key, now)
        if not owner.deleted or owner.current_job_id != lease.job_id:
            raise jobs.PermanentFailure("Cleanup is no longer current")
        active = session.execute(
            update(Job)
            .where(
                Job.id == lease.job_id,
                Job.resource_key == key,
                Job.kind == "delete_file",
                Job.state == "running",
                Job.lease_token == lease.token,
                Job.lease_deadline > now,
            )
            .values(lease_token=lease.token)
        )
        if not active.rowcount:
            raise jobs.PermanentFailure("Job lease is no longer active")
        if referenced(session, key):
            raise jobs.PermanentFailure("File is still referenced")
        session.commit()
    # Tombstones prohibit new attachment references after the authorization transaction.
    if not storage_service.is_enabled() or not storage_service.delete_file(key):
        raise RuntimeError("Storage deletion was not acknowledged")
    return {"deleted": True}
