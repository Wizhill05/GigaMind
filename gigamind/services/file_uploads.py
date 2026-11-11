"""Atomic preparation of immutable file uploads; remote transfer is separate."""

from datetime import datetime, timezone
import hashlib
import re

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from gigamind.db.database import StorageFileItem
from gigamind.db.jobs import Job, UploadManifest
from gigamind.services import jobs
from gigamind.services.file_lifecycle import validate_key

PREPARED_UNTIL = datetime(9999, 1, 1, tzinfo=timezone.utc)


def _snapshot(file, job):
    return file.model_dump(), job.model_dump(exclude={"lease_token"})


def _prepare_upload(
    key,
    filename,
    mime_type,
    multimodal_type,
    size_bytes,
    source_agent,
    idempotency_key,
    *,
    sha256=None,
    engine=None,
    clock=jobs.utcnow,
):
    """Register validated metadata and a deferred job, returning committed snapshots."""
    validate_key(key)
    if sha256 is not None:
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("sha256 must be a lowercase SHA256 hex digest")
        if type(size_bytes) is not int or not 0 <= size_bytes <= 20_000_000:
            raise ValueError("size_bytes must be an integer between 0 and 20000000")
    if not idempotency_key:
        raise ValueError("An idempotency key is required")
    values = dict(
        filename=filename,
        mime_type=mime_type,
        multimodal_type=multimodal_type,
        size_bytes=size_bytes,
        source_agent=source_agent,
    )
    instant = clock()
    now = jobs.stamp(instant)
    with Session(jobs.resolve_engine(engine), expire_on_commit=False) as session:
        owner = jobs.lock_resource(session, key, now)
        if owner.deleted:
            raise HTTPException(409, "File has been deleted")
        existing = session.exec(
            select(StorageFileItem).where(StorageFileItem.key == key)
        ).first()
        if existing:
            manifest = session.get(UploadManifest, key)
            old = session.exec(
                select(Job).where(Job.idempotency_key == idempotency_key)
            ).first()
            if (
                not old
                or old.kind != "index_file"
                or old.resource_key != key
                or old.id != existing.id
                or any(
                    getattr(existing, name) != value for name, value in values.items()
                )
                or (manifest.sha256 if manifest else None) != sha256
            ):
                raise jobs.Conflict("File key already registered")
            session.commit()
            return _snapshot(existing, old)
        if session.exec(
            select(Job.id).where(Job.idempotency_key == idempotency_key)
        ).first():
            raise jobs.Conflict("Idempotency key already used")
        job = jobs.enqueue_in_session(
            session,
            "index_file",
            {"key": key},
            idempotency_key,
            clock=lambda: instant,
            not_before=PREPARED_UNTIL,
        )
        # An idempotency key used by an earlier job cannot create new metadata.
        if owner.current_job_id != job.id:
            raise jobs.Conflict("Idempotency key already used")
        file = StorageFileItem(
            id=job.id,
            key=key,
            indexing_status="pending",
            created_at=now,
            updated_at=now,
            **values,
        )
        session.add(file)
        if sha256 is not None:
            session.add(
                UploadManifest(
                    key=key, job_id=job.id, sha256=sha256, size_bytes=size_bytes
                )
            )
        session.commit()
        return _snapshot(file, job)


def prepare_upload(
    key,
    filename,
    mime_type,
    multimodal_type,
    size_bytes,
    source_agent,
    idempotency_key,
    *,
    sha256=None,
    engine=None,
    clock=jobs.utcnow,
):
    try:
        return _prepare_upload(
            key,
            filename,
            mime_type,
            multimodal_type,
            size_bytes,
            source_agent,
            idempotency_key,
            sha256=sha256,
            engine=engine,
            clock=clock,
        )
    except IntegrityError as exc:
        raise jobs.Conflict(
            "Upload registration conflicts with an existing record"
        ) from exc


def acknowledge_upload(key, job_id, *, engine=None, clock=jobs.utcnow):
    """Make the still-current prepared job eligible after confirmed remote upload."""
    validate_key(key)
    now = jobs.stamp(clock())
    with Session(jobs.resolve_engine(engine), expire_on_commit=False) as session:
        owner = jobs.lock_resource(session, key, now)
        job = session.get(Job, job_id)
        manifest = session.get(UploadManifest, key)
        if owner.deleted:
            raise HTTPException(409, "File has been deleted")
        if (
            owner.current_job_id != job_id
            or not job
            or job.kind != "index_file"
            or job.resource_key != key
            or (
                manifest is not None
                and (manifest.job_id != job_id or manifest.state != "verified")
            )
            or job.state not in {"queued", "running", "retrying", "completed", "failed"}
            or session.exec(
                select(StorageFileItem.id).where(StorageFileItem.key == key)
            ).first()
            != job_id
        ):
            raise jobs.Conflict("Upload preparation is no longer current")
        if job.state == "queued" and job.available_at == jobs.stamp(PREPARED_UNTIL):
            job.available_at = now
            job.updated_at = now
        session.commit()
        return job.model_dump(exclude={"lease_token"})


def begin_upload(key, job_id, *, engine=None, clock=jobs.utcnow):
    """Admit one PUT. True grants ownership; False means no PUT is allowed."""
    validate_key(key)
    with Session(jobs.resolve_engine(engine)) as session:
        owner = jobs.lock_resource(session, key, jobs.stamp(clock()))
        manifest = session.get(UploadManifest, key)
        job = session.get(Job, job_id)
        if (
            owner.deleted
            or owner.current_job_id != job_id
            or not manifest
            or manifest.job_id != job_id
            or manifest.state != "prepared"
            or not job
            or job.state != "queued"
        ):
            session.commit()
            return False
        result = session.execute(
            update(UploadManifest)
            .where(
                UploadManifest.key == key,
                UploadManifest.job_id == job_id,
                UploadManifest.state == "prepared",
            )
            .values(state="inflight")
        )
        session.commit()
        return result.rowcount == 1


def record_unknown(
    key, job_id, *, engine=None, clock=jobs.utcnow, require_current=False
):
    """Record an uncertain PUT outcome without granting another PUT."""
    validate_key(key)
    with Session(jobs.resolve_engine(engine)) as session:
        owner = jobs.lock_resource(session, key, jobs.stamp(clock()))
        manifest = session.get(UploadManifest, key)
        if (
            (require_current and (owner.deleted or owner.current_job_id != job_id))
            or not manifest
            or manifest.job_id != job_id
            or manifest.state not in {"inflight", "unknown", "verified"}
        ):
            raise jobs.Conflict("Upload is not in flight")
        manifest.state = "unknown"
        session.commit()


def verify_upload(
    key, job_id, remote_bytes, *, engine=None, clock=jobs.utcnow, require_current=False
):
    """Verify fetched remote bytes; a missing or mismatched object remains unresolved."""
    validate_key(key)
    if remote_bytes is not None and not isinstance(remote_bytes, bytes):
        raise ValueError("remote_bytes must be bytes or None")
    digest = (
        hashlib.sha256(remote_bytes).hexdigest()
        if remote_bytes is not None and len(remote_bytes) <= 20_000_000
        else None
    )
    with Session(jobs.resolve_engine(engine)) as session:
        owner = jobs.lock_resource(session, key, jobs.stamp(clock()))
        manifest = session.get(UploadManifest, key)
        if (
            (require_current and (owner.deleted or owner.current_job_id != job_id))
            or not manifest
            or manifest.job_id != job_id
            or manifest.state not in {"inflight", "unknown", "verified"}
        ):
            raise jobs.Conflict("Upload was not admitted")
        if (
            remote_bytes is None
            or len(remote_bytes) != manifest.size_bytes
            or digest != manifest.sha256
        ):
            manifest.state = "unknown"
            session.commit()
            return False
        manifest.state = "verified"
        session.commit()
        return True
