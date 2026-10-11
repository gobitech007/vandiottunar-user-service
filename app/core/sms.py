import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("vandi.sms")


class SmsSender:
    async def send_otp(self, phone: str, code: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleSms(SmsSender):
    """Development only: prints the OTP to the server log."""

    async def send_otp(self, phone: str, code: str) -> None:
        logger.warning("DEV OTP for %s: %s", phone, code)


class Msg91Sms(SmsSender):
    """MSG91 OTP API. Check the current endpoint and DLT template rules in MSG91's docs before going live."""

    url = "https://control.msg91.com/api/v5/otp"

    async def send_otp(self, phone: str, code: str) -> None:
        s = get_settings()
        params = {"template_id": s.msg91_template_id, "mobile": phone.lstrip("+"), "otp": code}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(self.url, params=params, headers={"authkey": s.msg91_auth_key})
            resp.raise_for_status()


def get_sms_sender() -> SmsSender:
    return Msg91Sms() if get_settings().sms_provider == "msg91" else ConsoleSms()
