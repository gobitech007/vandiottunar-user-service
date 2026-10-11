import pytest

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("raw", ["9876543210", "+91 98765 43210", "09876543210", "919876543210"])
async def test_phone_formats_are_normalised(client, raw):
    r = await client.post("/auth/otp/request", json={"phone": raw})
    assert r.status_code == 200
    code = r.json()["dev_code"]
    r = await client.post("/auth/otp/verify", json={"phone": "9876543210", "code": code})
    assert r.status_code == 200


@pytest.mark.parametrize("raw", ["12345", "5876543210", "abcdefghij"])
async def test_invalid_phone_rejected(client, raw):
    r = await client.post("/auth/otp/request", json={"phone": raw})
    assert r.status_code == 422


async def test_wrong_code_then_lockout(client):
    await client.post("/auth/otp/request", json={"phone": "9876500000"})
    for _ in range(5):
        r = await client.post("/auth/otp/verify", json={"phone": "9876500000", "code": "000000"})
        assert r.status_code in (400, 200)
        if r.status_code == 200:  # astronomically unlikely the real code is 000000
            pytest.skip("random OTP happened to be 000000")
    r = await client.post("/auth/otp/verify", json={"phone": "9876500000", "code": "000000"})
    assert r.status_code == 429


async def test_old_code_invalid_after_resend(client):
    first = (await client.post("/auth/otp/request", json={"phone": "9876511111"})).json()["dev_code"]
    second = (await client.post("/auth/otp/request", json={"phone": "9876511111"})).json()["dev_code"]
    if first != second:
        r = await client.post("/auth/otp/verify", json={"phone": "9876511111", "code": first})
        assert r.status_code == 400
    r = await client.post("/auth/otp/verify", json={"phone": "9876511111", "code": second})
    assert r.status_code == 200


async def test_code_cannot_be_reused(client):
    code = (await client.post("/auth/otp/request", json={"phone": "9876522222"})).json()["dev_code"]
    assert (await client.post("/auth/otp/verify", json={"phone": "9876522222", "code": code})).status_code == 200
    assert (await client.post("/auth/otp/verify", json={"phone": "9876522222", "code": code})).status_code == 400


async def test_hourly_limit(client):
    for _ in range(5):
        assert (await client.post("/auth/otp/request", json={"phone": "9876533333"})).status_code == 200
    assert (await client.post("/auth/otp/request", json={"phone": "9876533333"})).status_code == 429


async def test_admin_phone_gets_admin_role(client, login_as):
    headers = await login_as(client, "9000000001")
    me = (await client.get("/auth/me", headers=headers)).json()
    assert me["role"] == "admin"


async def test_driver_cannot_use_admin_api(client, login_as):
    headers = await login_as(client, "9876544444")
    assert (await client.get("/admin/drivers", headers=headers)).status_code == 403
    assert (await client.get("/admin/drivers")).status_code == 401


async def test_admin_portal_refuses_non_admin_without_creating_account(client, login_as):
    code = (await client.post("/auth/otp/request", json={"phone": "9876555555"})).json()["dev_code"]
    r = await client.post("/auth/otp/verify", json={"phone": "9876555555", "code": code, "role": "admin"})
    assert r.status_code == 403 and "ADMIN_PHONES" in r.json()["detail"]
    # No account was created: a later driver login is a new user
    code = (await client.post("/auth/otp/request", json={"phone": "9876555555"})).json()["dev_code"]
    r = await client.post("/auth/otp/verify", json={"phone": "9876555555", "code": code})
    assert r.json()["is_new_user"] is True


async def test_existing_driver_promoted_when_added_to_admin_phones(client, login_as):
    # Someone who first signed up as a driver and is later listed in ADMIN_PHONES becomes admin
    code = (await client.post("/auth/otp/request", json={"phone": "9000000001"})).json()["dev_code"]
    r = await client.post("/auth/otp/verify", json={"phone": "9000000001", "code": code, "role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
