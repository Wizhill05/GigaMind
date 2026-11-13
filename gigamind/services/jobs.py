import json
import math
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from gigamind.db.jobs import Job, ResourceJobState, UploadManifest


def resolve_engine(engine):
    if engine is None:
        from gigamind.db import database

        return database.engine
    return engine


def validate_lease(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 1 <= value <= 86400
    ):
        raise ValueError("Invalid lease duration")


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


class Conflict(ValueError):
    pass


class PermanentFailure(Exception):
    pass


def lock_resource(session, key, now):
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    elif dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        raise RuntimeError("Unsupported database dialect")
    session.execute(
        insert(ResourceJobState)
        .values(key=key, deleted=False, created_at=now, updated_at=now)
        .on_conflict_do_nothing(index_elements=["key"])
    )
    session.execute(
        update(ResourceJobState).where(ResourceJobState.key == key).values(key=key)
    )
    return session.get(ResourceJobState, key)


def cancel_active(session, key, now):
    return session.execute(
        update(Job)
        .where(
            Job.resource_key == key,
            Job.kind.in_(["index_file", "delete_file"]),
            Job.state.in_(["queued", "retrying", "running"]),
        )
        .values(
            state="cancelled", lease_token=None, lease_deadline=None, updated_at=now
        )
    ).rowcount


class JobLease:
    def __init__(self, job_id, token, clock=utcnow, engine=None):
        self.job_id = job_id
        self.token = token
        self.clock = clock
        self.engine = engine

    def publication_guard(self, session):
        key = session.execute(
            select(Job.resource_key).where(Job.id == self.job_id)
        ).scalar_one_or_none()
        if key is None:
            raise PermanentFailure("Job resource is no longer current")
        owner = session.execute(
            update(ResourceJobState)
            .where(
                ResourceJobState.key == key,
                ResourceJobState.deleted.is_(False),
                ResourceJobState.current_job_id == self.job_id,
            )
            .values(key=key)
        )
        if not owner.rowcount:
            raise PermanentFailure("Job resource is no longer current")
        manifest = session.get(UploadManifest, key)
        if manifest is not None and manifest.state != "verified":
            raise PermanentFailure("Upload bytes have not been verified")
        result = session.execute(
            update(Job)
            .where(
                Job.id == self.job_id,
                Job.state == "running",
                Job.lease_token == self.token,
                Job.lease_deadline > stamp(self.clock()),
            )
            .values(lease_token=self.token)
        )
        if not result.rowcount:
            raise PermanentFailure("Job lease is no longer active")


def index_file(payload, lease):
    from gigamind.services.indexing import reindex_storage_file_by_key

    result = reindex_storage_file_by_key(
        payload["key"], publication_guard=lease.publication_guard
    )
    if not result:
        raise RuntimeError(
            "Storage unavailable or file missing; check storage configuration and file key"
        )
    status = result.get("status")
    if status in ("unsupported", "empty"):
        raise PermanentFailure("File is unsupported or contains no indexable text")
    if status != "completed":
        raise RuntimeError("Indexing did not complete; check indexing configuration")
    return result


def delete_file(payload, lease):
    from gigamind.services.file_lifecycle import cleanup_file

    return cleanup_file(payload["key"], lease)


def index_conversation(payload, lease):
    from gigamind.services.conversation_index import index_conversation as run

    return run(payload, lease)


HANDLERS = {
    "index_file": index_file,
    "delete_file": delete_file,
    "index_conversation": index_conversation,
}


def validate_resource_key(key):
    if not isinstance(key, str) or not key.strip() or len(key.encode("utf-8")) > 1024:
        raise ValueError("Resource key must be nonblank and at most 1024 UTF-8 bytes")


def enqueue_in_session(
    session,
    kind,
    payload,
    idempotency_key=None,
    max_attempts=3,
    *,
    clock=utcnow,
    not_before=None,
):
    """Enqueue in the caller's transaction without committing it."""
    if not_before is not None and (
        not isinstance(not_before, datetime) or not_before.utcoffset() is None
    ):
        raise ValueError("not_before must be a timezone-aware datetime")
    if kind != "index_file":
        raise ValueError("Unknown job kind")
    if kind == "index_file" and (
        not isinstance(payload, dict) or set(payload) != {"key"}
    ):
        raise ValueError("index_file requires a nonempty key")
    validate_resource_key(payload["key"])
    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= 20
        or (
            idempotency_key is not None
            and (
                not isinstance(idempotency_key, str)
                or not idempotency_key.strip()
                or len(idempotency_key) > 255
            )
        )
    ):
        raise ValueError("Invalid job options")
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    now = stamp(clock())
    job = Job(
        id=uuid.uuid4().hex,
        kind=kind,
        resource_key=payload["key"],
        payload_json=encoded,
        idempotency_key=idempotency_key,
        state="queued",
        max_attempts=max_attempts,
        available_at=stamp(not_before) if not_before is not None else now,
        created_at=now,
        updated_at=now,
    )
    owner = lock_resource(session, payload["key"], now)
    if idempotency_key is not None:
        old = session.exec(
            select(Job).where(Job.idempotency_key == idempotency_key)
        ).first()
        if old is not None:
            if (
                old.kind != kind
                or old.payload_json != encoded
                or old.max_attempts != max_attempts
            ):
                raise Conflict(
                    "Idempotency key already used with different job parameters"
                )
            return old
    if owner.deleted:
        raise Conflict("Resource has been forgotten")
    cancel_active(session, payload["key"], now)
    session.add(job)
    owner.current_job_id = job.id
    owner.updated_at = now
    session.flush()
    return job


def enqueue(
    kind, payload, idempotency_key=None, max_attempts=3, *, engine=None, clock=utcnow
):
    with Session(resolve_engine(engine), expire_on_commit=False) as session:
        try:
            job = enqueue_in_session(
                session, kind, payload, idempotency_key, max_attempts, clock=clock
            )
            session.commit()
            return job
        except IntegrityError:
            session.rollback()
            if idempotency_key is None:
                raise
            old = session.exec(
                select(Job).where(Job.idempotency_key == idempotency_key)
            ).first()
            if old is None:
                raise
            encoded = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            if (
                old.kind != kind
                or old.payload_json != encoded
                or old.max_attempts != max_attempts
            ):
                raise Conflict(
                    "Idempotency key already used with different job parameters"
                )
            return old


def status(job_id, *, engine=None):
    with Session(resolve_engine(engine)) as session:
        return session.get(Job, job_id)


def claim(*, engine=None, clock=utcnow, lease_seconds=60):
    validate_lease(lease_seconds)
    now = clock()
    current = stamp(now)
    eligible = or_(
        and_(Job.state.in_(["queued", "retrying"]), Job.available_at <= current),
        and_(Job.state == "running", Job.lease_deadline <= current),
    )
    with Session(resolve_engine(engine), expire_on_commit=False) as session:
        session.execute(
            update(Job)
            .where(
                Job.state == "running",
                Job.lease_deadline <= current,
                Job.attempts >= Job.max_attempts,
            )
            .values(
                state="failed",
                error="Worker lease expired after final attempt",
                lease_token=None,
                lease_deadline=None,
                updated_at=current,
            )
        )
        session.commit()
        ids = session.exec(
            select(Job.id)
            .where(eligible)
            .order_by(Job.available_at, Job.created_at, Job.id)
            .limit(20)
        ).all()
        for job_id in ids:
            token = uuid.uuid4().hex
            result = session.execute(
                update(Job)
                .where(Job.id == job_id, eligible)
                .values(
                    state="running",
                    lease_token=token,
                    lease_deadline=stamp(now + timedelta(seconds=lease_seconds)),
                    attempts=Job.attempts + 1,
                    updated_at=current,
                )
            )
            if result.rowcount:
                claimed = session.get(Job, job_id)
                session.commit()
                return claimed
            session.commit()
    return None


def guarded(job_id, token, values, *, engine=None, clock=utcnow):
    now = stamp(clock())
    with Session(resolve_engine(engine)) as session:
        result = session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.state == "running",
                Job.lease_token == token,
                Job.lease_deadline > now,
            )
            .values(**values, updated_at=now)
        )
        session.commit()
        return bool(result.rowcount)


def heartbeat(job_id, token, *, engine=None, clock=utcnow, lease_seconds=60):
    validate_lease(lease_seconds)
    return guarded(
        job_id,
        token,
        {"lease_deadline": stamp(clock() + timedelta(seconds=lease_seconds))},
        engine=engine,
        clock=clock,
    )


def cancel(job_id, *, engine=None, clock=utcnow):
    with Session(resolve_engine(engine)) as session:
        result = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.state.in_(["queued", "retrying", "running"]))
            .values(
                state="cancelled",
                lease_token=None,
                lease_deadline=None,
                updated_at=stamp(clock()),
            )
        )
        session.commit()
        return bool(result.rowcount)


def cancel_resource(key, *, engine=None, clock=utcnow):
    validate_resource_key(key)
    with Session(resolve_engine(engine)) as session:
        now = stamp(clock())
        lock_resource(session, key, now)
        count = cancel_active(session, key, now)
        session.commit()
        return count


def forget_resource(key, *, engine=None, clock=utcnow):
    validate_resource_key(key)
    with Session(resolve_engine(engine)) as session:
        now = stamp(clock())
        owner = lock_resource(session, key, now)
        owner.deleted = True
        owner.current_job_id = None
        owner.updated_at = now
        count = cancel_active(session, key, now)
        session.commit()
        return count


def run_once(*, engine=None, clock=utcnow, lease_seconds=60):
    job = claim(engine=engine, clock=clock, lease_seconds=lease_seconds)
    if not job:
        return None
    stop = threading.Event()

    def renew():
        while not stop.wait(max(0.1, lease_seconds / 3)):
            if not heartbeat(
                job.id,
                job.lease_token,
                engine=engine,
                clock=clock,
                lease_seconds=lease_seconds,
            ):
                break

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        result = HANDLERS[job.kind](
            json.loads(job.payload_json),
            JobLease(job.id, job.lease_token, clock, engine),
        )
        values = {
            "state": "completed",
            "result_json": json.dumps(result),
            "error": None,
        }
    except Exception as exc:
        terminal = isinstance(exc, PermanentFailure) or job.attempts >= job.max_attempts
        values = {
            "state": "failed" if terminal else "retrying",
            "error": "Job failed; check worker configuration",
            "available_at": stamp(
                clock() + timedelta(seconds=min(300, 2 ** (job.attempts - 1)))
            ),
        }
    finally:
        stop.set()
        thread.join()
    values.update(lease_token=None, lease_deadline=None)
    guarded(job.id, job.lease_token, values, engine=engine, clock=clock)
    return status(job.id, engine=engine)
