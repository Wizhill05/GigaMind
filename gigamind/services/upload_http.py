"""Upload orchestration, with no database transaction across storage IO."""

import hashlib
import mimetypes
import re
import uuid

from fastapi import HTTPException
from sqlmodel import Session

from gigamind.db.jobs import Job, ResourceJobState, UploadManifest
from gigamind.security import Actor
from gigamind.services import file_uploads, jobs
from gigamind.services.file_lifecycle import validate_key
from gigamind.services.storage import storage_service

LIMIT = 20_000_000


def recover(key, job_id, *, actor=None):
    validate_key(key)
    with Session(jobs.resolve_engine(None)) as session:
        owner = session.get(ResourceJobState, key)
        manifest = session.get(UploadManifest, key)
        job = session.get(Job, job_id)
        if (
            not owner
            or owner.deleted
            or owner.current_job_id != job_id
            or not manifest
            or manifest.job_id != job_id
            or manifest.state not in {"inflight", "unknown", "verified"}
            or not job
            or job.resource_key != key
        ):
            raise HTTPException(409, "Upload is no longer current")
    try:
        data = storage_service.get_bounded_object(key)
    except Exception:
        try:
            file_uploads.record_unknown(key, job_id, require_current=True)
        except jobs.Conflict:
            raise HTTPException(409, "Upload is no longer current") from None
        except Exception:
            pass
        raise HTTPException(
            503,
            {
                "message": "Upload verification unavailable",
                "key": key,
                "job_id": job_id,
            },
        ) from None
    try:
        verified = file_uploads.verify_upload(
            key, job_id, data, actor=actor, require_current=True
        )
    except jobs.Conflict:
        raise HTTPException(409, "Upload is no longer current") from None
    except Exception:
        raise HTTPException(
            503,
            {
                "message": "Upload verification unavailable",
                "key": key,
                "job_id": job_id,
            },
        ) from None
    if not verified:
        raise HTTPException(
            409, {"message": "Upload verification failed", "key": key, "job_id": job_id}
        )
    try:
        job = file_uploads.acknowledge_upload(key, job_id)
    except jobs.Conflict:
        with Session(jobs.resolve_engine(None)) as session:
            owner = session.get(ResourceJobState, key)
            current = session.get(Job, job_id)
            if (
                owner
                and not owner.deleted
                and owner.current_job_id == job_id
                and current
                and current.state == "cancelled"
            ):
                return {
                    "key": key,
                    "job_id": job_id,
                    "state": "cancelled",
                    "verified": True,
                }
        raise HTTPException(409, "Upload is no longer current") from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            503,
            {
                "message": "Upload acknowledgement unavailable",
                "key": key,
                "job_id": job_id,
            },
        ) from None
    return {"key": key, "job_id": job_id, "state": job["state"], "verified": True}


def upload(data, filename, mime_type, prefix, actor):
    if not isinstance(actor, Actor) or not actor.is_admin:
        raise HTTPException(403, "Admin required")
    if not storage_service.is_enabled():
        raise HTTPException(503, "Storage is not configured")
    if (
        not filename
        or not filename.strip()
        or len(filename) > 255
        or any(ord(c) < 32 or ord(c) == 127 for c in filename)
        or not prefix
        or len(prefix) > 200
        or not re.fullmatch(r"[A-Za-z0-9_/-]+", prefix)
    ):
        raise HTTPException(422, "Invalid upload metadata")
    if mime_type and (
        len(mime_type) > 255
        or not re.fullmatch(r"[A-Za-z0-9!#$&^_.+\-]+/[A-Za-z0-9!#$&^_.+\-]+", mime_type)
    ):
        raise HTTPException(422, "Invalid MIME type")
    if len(data) > LIMIT:
        raise HTTPException(413, "File exceeds size limit")
    mime_type = (
        mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    )
    key = storage_service.generate_storage_key(filename, prefix)
    validate_key(key)
    try:
        file, job = file_uploads.prepare_upload(
            key,
            filename,
            mime_type,
            "text",
            len(data),
            actor.id,
            uuid.uuid4().hex,
            sha256=hashlib.sha256(data).hexdigest(),
            actor=actor,
        )
    except jobs.Conflict as exc:
        raise HTTPException(409, str(exc)) from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Upload registration unavailable") from None
    try:
        if not file_uploads.begin_upload(key, job["id"]):
            raise jobs.Conflict("Upload admission denied")
    except jobs.Conflict:
        raise HTTPException(
            409, {"message": "Upload admission denied", "key": key, "job_id": job["id"]}
        ) from None
    except Exception:
        raise HTTPException(
            503,
            {
                "message": "Upload admission unavailable",
                "key": key,
                "job_id": job["id"],
            },
        ) from None
    try:
        storage_service.create_immutable_object(key, data, mime_type)
    except Exception:
        try:
            file_uploads.record_unknown(key, job["id"])
        except Exception:
            pass
        raise HTTPException(
            503, {"message": "Upload outcome unknown", "key": key, "job_id": job["id"]}
        ) from None
    result = recover(key, job["id"], actor=actor)
    if result["state"] == "cancelled":
        raise HTTPException(
            409,
            {
                "message": "Upload verified but cancelled",
                "key": key,
                "job_id": job["id"],
                "verified": True,
            },
        )
    return {
        "success": True,
        "file": file,
        "job_id": job["id"],
        "state": result["state"],
        "indexing": "queued",
    }
