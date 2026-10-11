import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import as_utc, create_access_token, generate_otp, hash_otp, otp_matches, utcnow
from app.core.sms import get_sms_sender
from app.db import get_session
from app.deps import get_current_user
from app.models import OtpCode, Role, User
from app.schemas import OtpRequestOut, OtpVerifyIn, PhoneIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("vandi.auth")

MAX_OTPS_PER_HOUR = 5


@router.post("/otp/request", response_model=OtpRequestOut)
async def request_otp(body: PhoneIn, session: AsyncSession = Depends(get_session)):
    s = get_settings()
    now = utcnow()

    latest = await session.scalar(
        select(OtpCode).where(OtpCode.phone == body.phone).order_by(OtpCode.created_at.desc()).limit(1)
    )
    if latest and (now - as_utc(latest.created_at)).total_seconds() < s.otp_resend_seconds:
        wait = s.otp_resend_seconds - int((now - as_utc(latest.created_at)).total_seconds())
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Please wait {wait}s before requesting a new code")

    recent = await session.scalar(
        select(func.count()).select_from(OtpCode).where(
            OtpCode.phone == body.phone, OtpCode.created_at >= now - timedelta(hours=1)
        )
    )
    if recent and recent >= MAX_OTPS_PER_HOUR:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many codes requested. Try again in an hour.")

    # Only the newest code is ever valid
    await session.execute(
        update(OtpCode).where(OtpCode.phone == body.phone, OtpCode.consumed.is_(False)).values(consumed=True)
    )
    code = generate_otp()
    session.add(
        OtpCode(
            phone=body.phone,
            code_hash=hash_otp(body.phone, code),
            expires_at=now + timedelta(seconds=s.otp_ttl_seconds),
        )
    )
    await session.commit()

    try:
        await get_sms_sender().send_otp(body.phone, code)
    except Exception:
        logger.exception("Failed to send OTP to %s", body.phone)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not send the SMS. Please try again.")

    dev_code = code if (not s.is_production and s.sms_provider == "console") else None
    return OtpRequestOut(message="Code sent", resend_after_seconds=s.otp_resend_seconds, dev_code=dev_code)


@router.post("/otp/verify", response_model=TokenOut)
async def verify_otp(body: OtpVerifyIn, session: AsyncSession = Depends(get_session)):
    s = get_settings()
    otp = await session.scalar(
        select(OtpCode)
        .where(OtpCode.phone == body.phone, OtpCode.consumed.is_(False))
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    if otp is None or as_utc(otp.expires_at) < utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This code has expired or was already used. Please request a new one.")
    if otp.attempts >= s.otp_max_attempts:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many wrong attempts. Request a new code.")
    if not otp_matches(body.phone, body.code, otp.code_hash):
        otp.attempts += 1
        await session.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Wrong code. Please check and try again.")

    otp.consumed = True
    if body.role == "admin" and body.phone not in s.admin_phone_set:
        # Never create an account from the admin sign-in page
        await session.commit()
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This number is not an admin. Add it to ADMIN_PHONES and restart the API."
        )
    user = await session.scalar(select(User).where(User.phone == body.phone))
    is_new = user is None
    if user is None:
        user = User(phone=body.phone, role=Role(body.role), is_active=True)
        session.add(user)
    if body.phone in s.admin_phone_set:
        user.role = Role.admin
    if not user.is_active:
        await session.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is blocked. Contact support.")
    await session.commit()

    return TokenOut(
        access_token=create_access_token(user.id, user.role.value),
        user_id=user.id,
        role=user.role,
        is_new_user=is_new,
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
