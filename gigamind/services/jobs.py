import json
import math
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from gigamind.db.jobs import Job


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


class JobLease:
    def __init__(self, job_id, token, clock=utcnow):
        self.job_id = job_id
        self.token = token
        self.clock = clock

    def publication_guard(self, session):
        # An update takes a write lock on SQLite and a row lock on PostgreSQL.
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


HANDLERS = {"index_file": index_file}


def validate_resource_key(key):
    if not isinstance(key, str) or not key.strip() or len(key.encode("utf-8")) > 1024:
        raise ValueError("Resource key must be nonblank and at most 1024 UTF-8 bytes")


def enqueue(
    kind, payload, idempotency_key=None, max_attempts=3, *, engine=None, clock=utcnow
):
    if not isinstance(kind, str) or kind not in HANDLERS:
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
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    with Session(resolve_engine(engine)) as session:
        session.add(job)
        try:
            session.commit()
            session.refresh(job)
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
        result = session.execute(
            update(Job)
            .where(
                Job.resource_key == key,
                Job.state.in_(["queued", "retrying", "running"]),
            )
            .values(
                state="cancelled",
                lease_token=None,
                lease_deadline=None,
                updated_at=stamp(clock()),
            )
        )
        session.commit()
        return result.rowcount


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
            json.loads(job.payload_json), JobLease(job.id, job.lease_token, clock)
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
