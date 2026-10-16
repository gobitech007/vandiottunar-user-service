import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ocr
from app.core.config import get_settings
from app.core.security import utcnow
from app.core.storage import get_storage
from app.db import get_session
from app.deps import require_role
from app.models import Consent, DocumentType, DriverDocument, DriverProfile, DriverStatus, Role, User
from app.schemas import (
    ChecklistOut,
    ConsentIn,
    DocumentOut,
    AadhaarIn,
    AadhaarTextIn,
    LicenceIn,
    LicenceTextIn,
    LocationIn,
    ParsedAadhaarOut,
    ParsedLicenceOut,
    ProfileOut,
    ProfileUpdate,
)
from app.services import aadhaar
from app.services.licence import parse_licence_text
from app.services.timeutil import today_ist
from app.services.onboarding import build_checklist, get_or_create_profile

router = APIRouter(prefix="/drivers/me", tags=["driver onboarding"])
driver_only = require_role(Role.driver)

EDITABLE = {DriverStatus.draft, DriverStatus.rejected}

# content type -> (file extension, magic-byte check)
ALLOWED_FILES = {
    "image/jpeg": ("jpg", lambda b: b[:3] == b"\xff\xd8\xff"),
    "image/png": ("png", lambda b: b[:8] == b"\x89PNG\r\n\x1a\n"),
    "image/webp": ("webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
    "application/pdf": ("pdf", lambda b: b[:5] == b"%PDF-"),
}


def _ensure_editable(profile: DriverProfile) -> None:
    if profile.status not in EDITABLE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Your application is already submitted. Contact support to change details.",
        )


@router.get("", response_model=ProfileOut)
async def get_my_profile(user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)):
    return await get_or_create_profile(session, user)


@router.put("/profile", response_model=ProfileOut)
async def update_profile(
    body: ProfileUpdate, user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)
):
    profile = await get_or_create_profile(session, user)
    _ensure_editable(profile)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(profile, field, sorted(set(value)) if isinstance(value, list) else value)
    await session.commit()
    return profile


def _parsed_out(text: str, include_text: bool = False) -> ParsedLicenceOut:
    parsed = parse_licence_text(text)
    return ParsedLicenceOut(
        licence_number=parsed.licence_number,
        classes=parsed.classes,
        valid_till=parsed.valid_till,
        two_wheeler=parsed.two_wheeler,
        four_wheeler=parsed.four_wheeler,
        heavy=parsed.heavy,
        wording_found=parsed.wording_found,
        looks_like_licence=parsed.looks_like_licence,
        expired=parsed.expired(today_ist()),
        raw_text=text[:4000] if include_text else None,
    )


@router.post("/licence/parse", response_model=ParsedLicenceOut)
async def parse_licence(body: LicenceTextIn, user: User = Depends(driver_only)):
    """Turn OCR text from the browser or phone into a licence number and vehicle classes."""
    return _parsed_out(body.text)


@router.post("/licence/scan", response_model=ParsedLicenceOut)
async def scan_licence(user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)):
    """Read the uploaded licence photos with server OCR (AWS Textract when OCR_PROVIDER=textract)."""
    profile = await get_or_create_profile(session, user)
    text = await _server_text(profile, (DocumentType.licence_front, DocumentType.licence_back), "licence")
    return _parsed_out(text, include_text=True)


async def _server_text(profile: DriverProfile, types: tuple[DocumentType, ...], what: str) -> str:
    """OCR the driver's uploaded photos of these types on the server, in the given order."""
    docs = sorted((d for d in profile.documents if d.doc_type in types), key=lambda d: types.index(d.doc_type))
    if not docs:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Upload the {what} photo first")
    storage = get_storage()
    texts = []
    try:
        for doc in docs:
            texts.append(await ocr.read_text(await storage.read(doc.storage_key)))
    except ocr.OcrUnavailable:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Server photo reading is not enabled")
    except Exception:
        ocr.logger.exception("%s OCR failed", what)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not read the {what} photo. Please enter the details.")
    return "\n".join(texts)


def _aadhaar_out(text: str) -> ParsedAadhaarOut:
    number = aadhaar.find_aadhaar(text)
    return ParsedAadhaarOut(
        aadhaar_number=number,
        masked=aadhaar.mask(number) if number else None,
        wording_found=aadhaar.has_aadhaar_wording(text),
    )


@router.post("/aadhaar/parse", response_model=ParsedAadhaarOut)
async def parse_aadhaar(body: AadhaarTextIn, user: User = Depends(driver_only)):
    """Find the Aadhaar number in OCR text from the browser or phone. Nothing is stored."""
    return _aadhaar_out(body.text)


@router.post("/aadhaar/scan", response_model=ParsedAadhaarOut)
async def scan_aadhaar(user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)):
    """Read the uploaded ID photo with server OCR. Nothing is stored."""
    profile = await get_or_create_profile(session, user)
    return _aadhaar_out(await _server_text(profile, (DocumentType.id_proof,), "Aadhaar"))


@router.put("/aadhaar", response_model=ProfileOut)
async def save_aadhaar(body: AadhaarIn, user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)):
    """Checks the full number, then keeps only its last 4 digits."""
    profile = await get_or_create_profile(session, user)
    _ensure_editable(profile)
    profile.aadhaar_last4 = body.aadhaar_number[-4:]
    profile.aadhaar_source = body.source
    await session.commit()
    return profile


@router.put("/licence", response_model=ProfileOut)
async def save_licence(body: LicenceIn, user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)):
    profile = await get_or_create_profile(session, user)
    _ensure_editable(profile)
    if body.valid_till and body.valid_till < today_ist():
        raise HTTPException(
            422,
            f"This licence expired on {body.valid_till:%d-%m-%Y}. Renew it before registering.",
        )
    profile.licence_number = body.licence_number
    profile.licence_classes = body.classes
    profile.licence_valid_till = body.valid_till
    profile.licence_source = body.source
    profile.licence_raw_text = body.raw_text
    profile.licence_verified = False  # any change needs a fresh admin check
    await session.commit()
    return profile


@router.put("/location", response_model=ProfileOut)
async def set_location(body: LocationIn, user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)):
    profile = await get_or_create_profile(session, user)
    _ensure_editable(profile)
    profile.registration_lat = body.lat
    profile.registration_lng = body.lng
    profile.registration_accuracy_m = body.accuracy_m
    profile.location_captured_at = utcnow()
    profile.city = body.city
    profile.home_pincode = body.home_pincode
    profile.home_area = body.home_area
    # Home/work location defaults to where they are now, but they can pick another spot on the map
    profile.home_lat = body.home_lat if body.home_lat is not None else body.lat
    profile.home_lng = body.home_lng if body.home_lng is not None else body.lng
    profile.service_radius_km = body.service_radius_km
    await session.commit()
    return profile


@router.post("/consent", status_code=status.HTTP_201_CREATED)
async def accept_consent(
    body: ConsentIn, request: Request, user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)
):
    current = get_settings().consent_version
    if body.version != current:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Please accept the latest notice (version {current})")
    session.add(
        Consent(
            user_id=user.id,
            version=current,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "")[:255],
        )
    )
    await session.commit()
    return {"version": current}


@router.post("/documents/{doc_type}", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    doc_type: DocumentType,
    file: UploadFile = File(...),
    user: User = Depends(driver_only),
    session: AsyncSession = Depends(get_session),
):
    profile = await get_or_create_profile(session, user)
    _ensure_editable(profile)

    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"File must be under {get_settings().max_upload_mb} MB")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty")

    content_type = (file.content_type or "").lower()
    allowed = ALLOWED_FILES.get(content_type)
    if allowed is None or not allowed[1](data):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a JPG, PNG, WEBP photo or a PDF")
    if doc_type == DocumentType.selfie and content_type == "application/pdf":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "The selfie must be a photo")

    key = f"drivers/{profile.id}/{doc_type.value}-{uuid.uuid4().hex}.{allowed[0]}"
    await get_storage().save(key, data, content_type)

    existing = next((d for d in profile.documents if d.doc_type == doc_type), None)
    if existing:
        existing.storage_key = key
        existing.content_type = content_type
        existing.size_bytes = len(data)
        existing.uploaded_at = utcnow()
        doc = existing
    else:
        doc = DriverDocument(
            driver_id=profile.id, doc_type=doc_type, storage_key=key, content_type=content_type, size_bytes=len(data)
        )
        session.add(doc)
    await session.commit()
    return doc


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)):
    profile = await get_or_create_profile(session, user)
    return profile.documents


@router.get("/checklist", response_model=ChecklistOut)
async def checklist(user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)):
    profile = await get_or_create_profile(session, user)
    return await build_checklist(session, profile)


@router.post("/submit", response_model=ProfileOut)
async def submit(user: User = Depends(driver_only), session: AsyncSession = Depends(get_session)):
    profile = await get_or_create_profile(session, user)
    _ensure_editable(profile)
    check = await build_checklist(session, profile)
    if not check.ready_to_submit:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "Some details are still missing", "checklist": check.model_dump(mode="json")},
        )
    profile.status = DriverStatus.submitted
    profile.submitted_at = utcnow()
    profile.rejection_reason = None
    await session.commit()
    return profile
