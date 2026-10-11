import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="vandi-test-")
os.environ.update(
    {
        "ENVIRONMENT": "development",
        # Set TEST_DATABASE_URL to run against PostgreSQL; defaults to a throwaway SQLite file
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_tmp}/test.db"),
        "JWT_SECRET": "test-secret-that-is-long-enough-for-hs256-0123456789",
        "SMS_PROVIDER": "console",
        "STORAGE_BACKEND": "local",
        "LOCAL_STORAGE_DIR": f"{_tmp}/uploads",
        "ADMIN_PHONES": "+919000000001",
        "OTP_RESEND_SECONDS": "0",
    }
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PDF = b"%PDF-1.4\n" + b"0" * 200


@pytest_asyncio.fixture(autouse=True)
async def fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def login(client: AsyncClient, phone: str, role: str = "driver") -> dict:
    r = await client.post("/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200, r.text
    code = r.json()["dev_code"]
    r = await client.post("/auth/otp/verify", json={"phone": phone, "code": code, "role": role})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def login_as():
    return login
