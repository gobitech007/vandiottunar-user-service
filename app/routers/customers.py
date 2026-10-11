from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require_role
from app.models import CustomerProfile, Role, User
from app.schemas import CustomerOut, CustomerUpdate

router = APIRouter(prefix="/customers/me", tags=["customers"])
customer_only = require_role(Role.customer, Role.employer)


def is_complete(profile: CustomerProfile, role: Role) -> bool:
    base = bool(profile.full_name and profile.home_pincode and profile.needs)
    return base and (role != Role.employer or bool(profile.company_name))


def to_out(profile: CustomerProfile, role: Role) -> CustomerOut:
    data = {c: getattr(profile, c) for c in CustomerOut.model_fields if c != "profile_complete"}
    data["needs"] = profile.needs or []
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
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(profile, field, sorted(set(value)) if isinstance(value, list) else value)
    await session.commit()
    return to_out(profile, user.role)
