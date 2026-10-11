from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import REQUIRED_DOCUMENTS, Consent, DriverProfile, User
from app.schemas import ChecklistOut

REQUIRED_FIELDS = ("full_name", "licence_number", "experience_years", "vehicle_types", "availability", "work_preferences")


async def _find_profile(session: AsyncSession, user_id: str) -> DriverProfile | None:
    return await session.scalar(
        select(DriverProfile)
        .options(selectinload(DriverProfile.documents))
        .where(DriverProfile.user_id == user_id)
        .execution_options(populate_existing=True)
    )


async def get_or_create_profile(session: AsyncSession, user: User) -> DriverProfile:
    user_id = user.id
    profile = await _find_profile(session, user_id)
    if profile is None:
        session.add(DriverProfile(user_id=user_id, vehicle_types=[], work_preferences=[]))
        try:
            await session.commit()
        except IntegrityError:
            # Another request (the apps load profile and checklist in parallel) created it first
            await session.rollback()
            await session.refresh(user)
        profile = await _find_profile(session, user_id)
    return profile


async def latest_consent(session: AsyncSession, user_id: str) -> Consent | None:
    return await session.scalar(
        select(Consent).where(Consent.user_id == user_id).order_by(Consent.accepted_at.desc()).limit(1)
    )


async def build_checklist(session: AsyncSession, profile: DriverProfile) -> ChecklistOut:
    version = get_settings().consent_version
    missing_fields = [f for f in REQUIRED_FIELDS if getattr(profile, f) in (None, "", [])]
    have_docs = {d.doc_type for d in profile.documents}
    missing_docs = [d for d in REQUIRED_DOCUMENTS if d not in have_docs]
    location_ok = profile.registration_lat is not None and profile.home_pincode is not None
    consent = await latest_consent(session, profile.user_id)
    consent_ok = consent is not None and consent.version == version
    return ChecklistOut(
        profile_complete=not missing_fields,
        location_captured=location_ok,
        consent_accepted=consent_ok,
        missing_documents=missing_docs,
        missing_fields=missing_fields,
        ready_to_submit=not missing_fields and not missing_docs and location_ok and consent_ok,
        current_consent_version=version,
    )
