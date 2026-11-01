import hashlib
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from incidentiq.api.dependencies import get_db
from incidentiq.models import EvidenceSource, Incident
from incidentiq.schemas.evidence import EvidenceRead, EvidenceType

router = APIRouter(prefix="/incidents/{incident_id}/evidence", tags=["evidence"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MiB
READ_CHUNK_BYTES = 64 * 1024
MAX_FILENAME_LENGTH = 255  # evidence_sources.source_name is VARCHAR(255)
ALLOWED_EXTENSIONS = frozenset({".log", ".txt"})
STORED_CONTENT_TYPE = "text/plain; charset=utf-8"


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=f"File exceeds the maximum size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB.",
    )


def _duplicate() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="This evidence has already been uploaded for this incident.",
    )


def _incident_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")


def sanitize_filename(raw: str | None) -> str:
    """Return only the basename of a client-supplied filename, or raise 400."""
    if raw is None or not raw.strip():
        raise _bad_request("A filename is required.")
    # Treat Windows and POSIX separators alike and keep only the last component.
    name = raw.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."}:
        raise _bad_request("Invalid filename.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise _bad_request("Filename contains control characters.")
    if len(name) > MAX_FILENAME_LENGTH:
        raise _bad_request(f"Filename is longer than {MAX_FILENAME_LENGTH} characters.")
    return name


def _validate_extension(name: str) -> None:
    if PurePosixPath(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise _bad_request("Unsupported file type. Only .log and .txt files are accepted.")


async def _read_bounded(upload: UploadFile) -> bytes:
    """Read the upload in chunks, aborting as soon as the size limit is exceeded."""
    if upload.size is not None and upload.size > MAX_UPLOAD_BYTES:
        raise _too_large()
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise _too_large()
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_text(data: bytes) -> str:
    if not data:
        raise _bad_request("Uploaded file is empty.")
    if b"\x00" in data:
        raise _bad_request("File contains NUL bytes and cannot be stored as text.")
    try:
        return data.decode("utf-8")  # strict: never replace invalid bytes
    except UnicodeDecodeError:
        raise _bad_request("File is not valid UTF-8 text.") from None


def _require_incident(db: Session, incident_id: UUID) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise _incident_not_found()
    return incident


def _duplicate_exists(db: Session, incident_id: UUID, content_hash: str) -> bool:
    found = db.scalar(
        select(EvidenceSource.id)
        .where(
            EvidenceSource.incident_id == incident_id,
            EvidenceSource.content_hash == content_hash,
        )
        .limit(1)
    )
    return found is not None


@router.post("", response_model=EvidenceRead, status_code=status.HTTP_201_CREATED)
async def upload_evidence(
    incident_id: UUID,
    file: Annotated[UploadFile, File()],
    evidence_type: Annotated[EvidenceType, Form()],
    db: Session = Depends(get_db),
) -> EvidenceSource:
    _require_incident(db, incident_id)

    source_name = sanitize_filename(file.filename)
    _validate_extension(source_name)

    data = await _read_bounded(file)
    text = _decode_text(data)
    content_hash = hashlib.sha256(data).hexdigest()  # hash of the original bytes

    if _duplicate_exists(db, incident_id, content_hash):
        raise _duplicate()

    evidence = EvidenceSource(
        incident_id=incident_id,
        source_name=source_name,
        evidence_type=evidence_type,
        content_type=STORED_CONTENT_TYPE,
        raw_content=text,
        content_hash=content_hash,
        byte_size=len(data),
        parse_status="not_required",
        created_at=datetime.now(timezone.utc),
    )
    db.add(evidence)
    try:
        db.commit()
    except IntegrityError:
        # Always leave the session usable, then work out what actually failed.
        db.rollback()
        if db.get(Incident, incident_id) is None:
            raise _incident_not_found() from None
        if _duplicate_exists(db, incident_id, content_hash):
            raise _duplicate() from None
        raise
    db.refresh(evidence)
    return evidence


@router.get("", response_model=list[EvidenceRead])
def list_evidence(incident_id: UUID, db: Session = Depends(get_db)) -> list[EvidenceSource]:
    _require_incident(db, incident_id)
    statement = (
        select(EvidenceSource)
        .options(defer(EvidenceSource.raw_content))  # never load large bodies for lists
        .where(EvidenceSource.incident_id == incident_id)
        .order_by(EvidenceSource.created_at.desc(), EvidenceSource.id.desc())
    )
    return list(db.scalars(statement).all())


@router.get("/{evidence_id}/content")
def get_evidence_content(
    incident_id: UUID, evidence_id: UUID, db: Session = Depends(get_db)
) -> Response:
    _require_incident(db, incident_id)
    evidence = db.scalar(
        select(EvidenceSource).where(
            EvidenceSource.id == evidence_id,
            EvidenceSource.incident_id == incident_id,
        )
    )
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found.")
    return Response(
        content=evidence.raw_content,
        media_type="text/plain; charset=utf-8",
        headers={"X-Content-Type-Options": "nosniff"},
    )