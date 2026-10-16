from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import utcnow
from app.db import get_session
from app.deps import require_role
from app.models import CustomerProfile, Role, User
from app.schemas import CustomerOut, CustomerUpdate

router = APIRouter(prefix="/customers/me", tags=["customers"])
customer_only = require_role(Role.customer, Role.employer)


def policy_ok(profile: CustomerProfile) -> bool:
    return profile.policy_version == get_settings().customer_policy_version


def is_complete(profile: CustomerProfile, role: Role) -> bool:
    base = bool(profile.full_name and profile.home_pincode and profile.needs) and policy_ok(profile)
    # Car owners need their car number; businesses need a company name
    if role == Role.employer:
        return base and bool(profile.company_name)
    return base and bool(profile.car_number)


def to_out(profile: CustomerProfile, role: Role) -> CustomerOut:
    computed = {"profile_complete", "current_policy_version", "policy_accepted"}
    data = {c: getattr(profile, c) for c in CustomerOut.model_fields if c not in computed}
    data["needs"] = profile.needs or []
    data["current_policy_version"] = get_settings().customer_policy_version
    data["policy_accepted"] = policy_ok(profile)
    return CustomerOut(**data, profile_complete=is_complete(profile, role))


async def get_or_create(session: AsyncSession, user: User) -> CustomerProfile:
    user_id, role = user.id, user.role
    profile = await session.scalar(select(CustomerProfile).where(CustomerProfile.user_id == user_id))
    if profile is None:
        # Sensible default: car owners want on-demand drivers, businesses want permanent drivers
        session.add(CustomerProfile(user_id=user_id, needs=["job"] if role == Role.employer else ["on_demand"]))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()  # created by a parallel request
            await session.refresh(user)
        profile = await session.scalar(select(CustomerProfile).where(CustomerProfile.user_id == user_id))
    return profile


@router.get("", response_model=CustomerOut)
async def get_me(user: User = Depends(customer_only), session: AsyncSession = Depends(get_session)):
    return to_out(await get_or_create(session, user), user.role)


@router.put("", response_model=CustomerOut)
async def update_me(body: CustomerUpdate, user: User = Depends(customer_only), session: AsyncSession = Depends(get_session)):
    profile = await get_or_create(session, user)
    values = body.model_dump(exclude_unset=True)
    accept = values.pop("accept_policy_version", None)
    if accept is not None:
        if accept != get_settings().customer_policy_version:
            raise HTTPException(400, "The policy has been updated. Please read and accept the latest version.")
        profile.policy_version = accept
        profile.policy_accepted_at = utcnow()
    for field, value in values.items():
        if value is not None:
            setattr(profile, field, sorted(set(value)) if isinstance(value, list) else value)
    await session.commit()
    return to_out(profile, user.role)
