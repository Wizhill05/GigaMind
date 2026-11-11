"""Atomic preparation of immutable file uploads; remote transfer is separate."""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from gigamind.db.database import StorageFileItem
from gigamind.db.jobs import Job
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
    engine=None,
    clock=jobs.utcnow,
):
    """Register validated metadata and a deferred job, returning committed snapshots."""
    validate_key(key)
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
        if owner.deleted:
            raise HTTPException(409, "File has been deleted")
        if (
            owner.current_job_id != job_id
            or not job
            or job.kind != "index_file"
            or job.resource_key != key
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
