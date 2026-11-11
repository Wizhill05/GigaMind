"""Durable, reference-aware file cleanup."""
import json
import uuid
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import delete, update
from sqlmodel import Session, select

from gigamind.db.database import MemoryItem, StorageChunkItem, StorageFileItem
from gigamind.db.jobs import Job, ResourceJobState
from gigamind.security import Actor
from gigamind.services import jobs


def owned_key(key):
    return isinstance(key, str) and bool(key) and not urlsplit(key).scheme and not key.startswith('//')


def referenced(session, key):
    for item in session.exec(select(MemoryItem)).all():
        if item.media_url == key:
            return True
        try:
            attachments = json.loads(item.attachments_json or '[]')
        except (TypeError, ValueError):
            return True
        if not isinstance(attachments, list):
            return True
        for attachment in attachments:
            if not isinstance(attachment, dict):
                return True
            if attachment.get('key') == key:
                return True
    return False


def request_delete(actor, key, engine=None):
    if not isinstance(actor, Actor) or actor.is_admin is not True:
        raise HTTPException(403, 'Admin required')
    jobs.validate_resource_key(key)
    if not owned_key(key):
        raise HTTPException(422, 'Invalid file key')
    now = jobs.stamp(jobs.utcnow())
    with Session(jobs.resolve_engine(engine), expire_on_commit=False) as session:
        owner = jobs.lock_resource(session, key, now)
        if referenced(session, key):
            raise HTTPException(409, 'File is still referenced')
        current = session.get(Job, owner.current_job_id) if owner.current_job_id else None
        if owner.deleted and current and current.kind == 'delete_file' and current.state in ('queued', 'running', 'retrying', 'completed'):
            session.commit()
            return current
        jobs.cancel_active(session, key, now)
        session.exec(delete(StorageChunkItem).where(StorageChunkItem.file_key == key))
        session.exec(delete(StorageFileItem).where(StorageFileItem.key == key))
        job = Job(id=uuid.uuid4().hex, kind='delete_file', resource_key=key,
                  payload_json=json.dumps({'key': key}), state='queued', max_attempts=3,
                  available_at=now, created_at=now, updated_at=now)
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
            raise jobs.PermanentFailure('Cleanup is no longer current')
        active = session.execute(update(Job).where(
            Job.id == lease.job_id, Job.resource_key == key, Job.kind == 'delete_file',
            Job.state == 'running', Job.lease_token == lease.token, Job.lease_deadline > now,
        ).values(lease_token=lease.token))
        if not active.rowcount:
            raise jobs.PermanentFailure('Job lease is no longer active')
        if referenced(session, key):
            raise jobs.PermanentFailure('File is still referenced')
        if not storage_service.is_enabled() or not storage_service.delete_file(key):
            raise RuntimeError('Storage deletion was not acknowledged')
        session.commit()
    return {'deleted': True}
