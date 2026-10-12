import pytest

from tests.test_onboarding import complete_application

pytestmark = pytest.mark.asyncio
TOKEN = "service-token-for-tests-0123456789abcdef"


@pytest.fixture
def service_token(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "service_token", TOKEN)
    return {"X-Service-Token": TOKEN}


async def test_internal_api_is_off_without_token(client):
    assert (await client.get("/internal/drivers")).status_code == 503


async def test_internal_api_rejects_wrong_token(client, service_token):
    assert (await client.get("/internal/drivers")).status_code == 401
    assert (await client.get("/internal/drivers", headers={"X-Service-Token": "nope"})).status_code == 401


async def test_internal_drivers_and_users(client, login_as, service_token):
    driver = await login_as(client, "9876599001")
    await complete_application(client, driver)
    await client.post("/drivers/me/submit", headers=driver)
    admin = await login_as(client, "9000000001")
    driver_id = (await client.get("/admin/drivers", headers=admin)).json()["items"][0]["id"]

    assert (await client.get("/internal/drivers", headers=service_token)).json() == []  # not approved yet
    await client.post(
        f"/admin/drivers/{driver_id}/approve", json={"police_verified": True, "licence_verified": True}, headers=admin
    )
    drivers = (await client.get("/internal/drivers", headers=service_token)).json()
    assert len(drivers) == 1
    d = drivers[0]
    assert d["phone"] == "+919876599001" and d["four_wheeler"] and d["home_lat"] is not None

    customer = await login_as(client, "9876599002", role="customer")
    await client.put("/customers/me", json={"full_name": "Priya", "car_number": "TN37AB1234"}, headers=customer)
    me = (await client.get("/auth/me", headers=customer)).json()
    u = (await client.get(f"/internal/users/{me['id']}", headers=service_token)).json()
    assert u["full_name"] == "Priya" and u["car_number"] == "TN37AB1234" and u["role"] == "customer"
    assert (await client.get("/internal/users/missing", headers=service_token)).status_code == 404
