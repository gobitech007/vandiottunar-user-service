from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from jwt import InvalidTokenError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import create_file_token, decode_token, utcnow
from app.core.storage import get_storage
from app.db import get_session
from app.deps import require_role
from app.models import CustomerProfile, DriverDocument, DriverProfile, DriverStatus, ReviewEvent, Role, User
from app.schemas import (
    AdminCustomer,
    AdminDocumentOut,
    AdminDriverDetail,
    AdminDriverSummary,
    ApproveIn,
    CustomerList,
    DriverList,
    NearbyDriver,
    ProfileOut,
    RejectIn,
    StatsOut,
)
from app.routers.customers import to_out
from app.services.geo import bounding_box, haversine_km
from app.services.onboarding import latest_consent

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require_role(Role.admin)


async def _load_driver(session: AsyncSession, driver_id: str) -> DriverProfile:
    profile = await session.scalar(
        select(DriverProfile)
        .options(selectinload(DriverProfile.documents), selectinload(DriverProfile.user))
        .where(DriverProfile.id == driver_id)
    )
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found")
    return profile


def _summary(p: DriverProfile) -> AdminDriverSummary:
    return AdminDriverSummary(
        id=p.id,
        full_name=p.full_name,
        phone=p.user.phone,
        status=p.status,
        home_pincode=p.home_pincode,
        home_area=p.home_area,
        experience_years=p.experience_years,
        work_preferences=p.work_preferences or [],
        police_verified=p.police_verified,
        submitted_at=p.submitted_at,
        created_at=p.created_at,
    )


@router.get("/drivers", response_model=DriverList)
async def list_drivers(
    status_filter: DriverStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(admin_only),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(DriverProfile).join(User).options(selectinload(DriverProfile.user))
    if status_filter:
        stmt = stmt.where(DriverProfile.status == status_filter)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(DriverProfile.full_name.ilike(like), User.phone.ilike(like), DriverProfile.home_pincode.ilike(like))
        )
    total = await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    order = DriverProfile.submitted_at.desc() if status_filter == DriverStatus.submitted else DriverProfile.created_at.desc()
    rows = (await session.scalars(stmt.order_by(order).limit(limit).offset(offset))).all()
    return DriverList(items=[_summary(p) for p in rows], total=total or 0)


@router.get("/drivers/nearby", response_model=list[NearbyDriver])
async def nearby_drivers(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=10, gt=0, le=100),
    status_filter: DriverStatus = Query(default=DriverStatus.approved, alias="status"),
    _: User = Depends(admin_only),
    session: AsyncSession = Depends(get_session),
):
    min_lat, max_lat, min_lng, max_lng = bounding_box(lat, lng, radius_km)
    rows = (
        await session.scalars(
            select(DriverProfile)
            .options(selectinload(DriverProfile.user))
            .where(
                DriverProfile.status == status_filter,
                DriverProfile.home_lat.between(min_lat, max_lat),
                DriverProfile.home_lng.between(min_lng, max_lng),
            )
        )
    ).all()
    result = []
    for p in rows:
        d = haversine_km(lat, lng, p.home_lat, p.home_lng)
        if d <= radius_km:
            result.append(
                NearbyDriver(
                    id=p.id,
                    full_name=p.full_name,
                    phone=p.user.phone,
                    distance_km=round(d, 2),
                    within_service_area=d <= p.service_radius_km,
                    vehicle_types=p.vehicle_types or [],
                    work_preferences=p.work_preferences or [],
                )
            )
    return sorted(result, key=lambda r: r.distance_km)[:50]


@router.get("/drivers/{driver_id}", response_model=AdminDriverDetail)
async def driver_detail(
    driver_id: str, request: Request, _: User = Depends(admin_only), session: AsyncSession = Depends(get_session)
):
    p = await _load_driver(session, driver_id)
    consent = await latest_consent(session, p.user_id)
    docs = [
        AdminDocumentOut(
            id=d.id,
            doc_type=d.doc_type,
            content_type=d.content_type,
            size_bytes=d.size_bytes,
            uploaded_at=d.uploaded_at,
            view_url=str(
                request.url_for("document_file", document_id=d.id).include_query_params(token=create_file_token(d.id))
            ),
        )
        for d in p.documents
    ]
    base = ProfileOut.model_validate(p).model_dump()
    return AdminDriverDetail(
        **base,
        phone=p.user.phone,
        police_reference=p.police_reference,
        registration_accuracy_m=p.registration_accuracy_m,
        documents=docs,
        consent_version=consent.version if consent else None,
        consent_accepted_at=consent.accepted_at if consent else None,
    )


@router.get("/documents/{document_id}/file", name="document_file")
async def document_file(document_id: str, token: str, session: AsyncSession = Depends(get_session)):
    try:
        payload = decode_token(token)
    except InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Link expired")
    if payload.get("typ") != "file" or payload.get("sub") != document_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Link expired")
    doc = await session.get(DriverDocument, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    storage = get_storage()
    url = storage.presigned_url(doc.storage_key)
    if url:
        return RedirectResponse(url)
    path = storage.local_path(doc.storage_key)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing")
    return FileResponse(path, media_type=doc.content_type, headers={"Cache-Control": "private, no-store"})


async def _record(session: AsyncSession, driver: DriverProfile, admin: User, action: str, note: str | None) -> None:
    driver.reviewed_at = utcnow()
    driver.reviewed_by = admin.id
    session.add(ReviewEvent(driver_id=driver.id, admin_id=admin.id, action=action, note=note))
    await session.commit()


@router.post("/drivers/{driver_id}/approve", response_model=AdminDriverSummary)
async def approve(
    driver_id: str, body: ApproveIn, admin: User = Depends(admin_only), session: AsyncSession = Depends(get_session)
):
    p = await _load_driver(session, driver_id)
    if p.status not in (DriverStatus.submitted, DriverStatus.suspended):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Can't approve a driver who is {p.status.value}")
    if not (body.police_verified or p.police_verified):
        raise HTTPException(
            422, "Police verification must be completed before approval"
        )
    if body.police_verified and not p.police_verified:
        p.police_verified = True
        p.police_verified_at = utcnow()
    if body.police_reference:
        p.police_reference = body.police_reference
    p.status = DriverStatus.approved
    p.rejection_reason = None
    await _record(session, p, admin, "approved", body.note)
    return _summary(p)


@router.post("/drivers/{driver_id}/reject", response_model=AdminDriverSummary)
async def reject(
    driver_id: str, body: RejectIn, admin: User = Depends(admin_only), session: AsyncSession = Depends(get_session)
):
    p = await _load_driver(session, driver_id)
    if p.status != DriverStatus.submitted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only submitted applications can be rejected")
    p.status = DriverStatus.rejected
    p.rejection_reason = body.reason
    await _record(session, p, admin, "rejected", body.reason)
    return _summary(p)


@router.post("/drivers/{driver_id}/suspend", response_model=AdminDriverSummary)
async def suspend(
    driver_id: str, body: RejectIn, admin: User = Depends(admin_only), session: AsyncSession = Depends(get_session)
):
    p = await _load_driver(session, driver_id)
    if p.status != DriverStatus.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only approved drivers can be suspended")
    p.status = DriverStatus.suspended
    p.rejection_reason = body.reason
    await _record(session, p, admin, "suspended", body.reason)
    return _summary(p)


@router.get("/stats", response_model=StatsOut)
async def stats(_: User = Depends(admin_only), session: AsyncSession = Depends(get_session)):
    by_status = dict(
        (s.value if hasattr(s, "value") else s, c)
        for s, c in (
            await session.execute(select(DriverProfile.status, func.count()).group_by(DriverProfile.status))
        ).all()
    )
    pincodes = (
        await session.execute(
            select(DriverProfile.home_pincode, func.count().label("n"))
            .where(DriverProfile.home_pincode.is_not(None))
            .group_by(DriverProfile.home_pincode)
            .order_by(func.count().desc())
            .limit(20)
        )
    ).all()
    return StatsOut(
        by_status={s.value: by_status.get(s.value, 0) for s in DriverStatus},
        signups_by_pincode=[{"pincode": p, "drivers": n} for p, n in pincodes],
    )


@router.get("/customers", response_model=CustomerList)
async def list_customers(
    q: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(admin_only),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(CustomerProfile).join(User).options(selectinload(CustomerProfile.user))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                CustomerProfile.full_name.ilike(like),
                CustomerProfile.company_name.ilike(like),
                User.phone.ilike(like),
                CustomerProfile.home_pincode.ilike(like),
            )
        )
    total = await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (await session.scalars(stmt.order_by(CustomerProfile.created_at.desc()).limit(limit).offset(offset))).all()
    items = [
        AdminCustomer(**to_out(c, c.user.role).model_dump(), phone=c.user.phone, role=c.user.role) for c in rows
    ]
    return CustomerList(items=items, total=total or 0)
