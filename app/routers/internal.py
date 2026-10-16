"""Endpoints for other Vandi Ottunar services (order-service). Not for browsers or apps.

Callers send the shared secret in the X-Service-Token header. When SERVICE_TOKEN is not set
these endpoints are switched off.
"""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db import get_session
from app.models import CustomerProfile, DriverProfile, DriverStatus, User
from app.schemas import InternalDriver, InternalUser


async def require_service(x_service_token: str | None = Header(default=None)) -> None:
    expected = get_settings().service_token
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Internal API is disabled (SERVICE_TOKEN not set)")
    if not x_service_token or not hmac.compare_digest(x_service_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid service token")


router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_service)])


def _driver(p: DriverProfile) -> InternalDriver:
    return InternalDriver(
        user_id=p.user_id,
        driver_id=p.id,
        full_name=p.full_name,
        phone=p.user.phone,
        status=p.status,
        city=p.city,
        home_pincode=p.home_pincode,
        home_area=p.home_area,
        home_lat=p.home_lat,
        home_lng=p.home_lng,
        service_radius_km=p.service_radius_km,
        vehicle_types=p.vehicle_types or [],
        licence_classes=p.licence_classes or [],
        two_wheeler=p.two_wheeler,
        four_wheeler=p.four_wheeler,
        heavy_vehicle=p.heavy_vehicle,
        work_preferences=p.work_preferences or [],
        availability=p.availability,
        experience_years=p.experience_years,
    )


@router.get("/drivers", response_model=list[InternalDriver])
async def drivers(
    status_filter: DriverStatus = Query(default=DriverStatus.approved, alias="status"),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.scalars(
            select(DriverProfile)
            .join(User)
            .options(selectinload(DriverProfile.user))
            .where(DriverProfile.status == status_filter, User.is_active.is_(True))
        )
    ).all()
    return [_driver(p) for p in rows]


@router.get("/users/{user_id}", response_model=InternalUser)
async def user_detail(user_id: str, session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    out = InternalUser(user_id=user.id, role=user.role, phone=user.phone, is_active=user.is_active)
    customer = await session.scalar(select(CustomerProfile).where(CustomerProfile.user_id == user.id))
    if customer:
        out.full_name = customer.full_name
        out.company_name = customer.company_name
        out.city = customer.city
        out.home_pincode = customer.home_pincode
        out.home_area = customer.home_area
        out.car_number = customer.car_number
        out.policy_accepted = customer.policy_version == get_settings().customer_policy_version
    driver = await session.scalar(select(DriverProfile).where(DriverProfile.user_id == user.id))
    if driver:
        out.full_name = driver.full_name
        out.city = driver.city
        out.home_pincode = driver.home_pincode
        out.home_area = driver.home_area
    return out
