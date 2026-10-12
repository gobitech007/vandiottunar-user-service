import pytest

pytestmark = pytest.mark.asyncio


async def test_customer_registration(client, login_as):
    headers = await login_as(client, "9876600001", role="customer")
    me = (await client.get("/customers/me", headers=headers)).json()
    assert me["needs"] == ["on_demand"] and me["profile_complete"] is False

    r = await client.put(
        "/customers/me",
        json={"full_name": "Priya R", "email": "priya@example.com", "home_pincode": "641004", "home_area": "Peelamedu",
              "vehicle_note": "Swift, manual", "car_number": "tn 37 ab 1234"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["profile_complete"] is True
    assert r.json()["car_number"] == "TN37AB1234"


async def test_employer_needs_company_name(client, login_as):
    headers = await login_as(client, "9876600002", role="employer")
    me = (await client.get("/customers/me", headers=headers)).json()
    assert me["needs"] == ["job"]
    r = await client.put("/customers/me", json={"full_name": "Arun S", "home_pincode": "641018"}, headers=headers)
    assert r.json()["profile_complete"] is False
    r = await client.put("/customers/me", json={"company_name": "Kovai Logistics"}, headers=headers)
    assert r.json()["profile_complete"] is True


async def test_customer_validation(client, login_as):
    headers = await login_as(client, "9876600003", role="customer")
    assert (await client.put("/customers/me", json={"email": "not-an-email"}, headers=headers)).status_code == 422
    assert (await client.put("/customers/me", json={"needs": ["teleport"]}, headers=headers)).status_code == 422
    assert (await client.put("/customers/me", json={"car_number": "HELLO"}, headers=headers)).status_code == 422
    assert (await client.put("/customers/me", json={"car_number": "22 BH 1234 AA"}, headers=headers)).status_code == 200


async def test_roles_are_kept_separate(client, login_as):
    driver = await login_as(client, "9876600004", role="driver")
    assert (await client.get("/customers/me", headers=driver)).status_code == 403
    customer = await login_as(client, "9876600005", role="customer")
    assert (await client.get("/drivers/me", headers=customer)).status_code == 403
    # An existing driver who logs in from the customer page stays a driver
    r = await client.post("/auth/otp/request", json={"phone": "9876600004"})
    r = await client.post("/auth/otp/verify", json={"phone": "9876600004", "code": r.json()["dev_code"], "role": "customer"})
    assert r.json()["role"] == "driver" and r.json()["is_new_user"] is False


async def test_admin_lists_customers(client, login_as):
    headers = await login_as(client, "9876600006", role="employer")
    await client.put("/customers/me", json={"full_name": "Meena", "company_name": "Sri Travels"}, headers=headers)
    admin = await login_as(client, "9000000001")
    data = (await client.get("/admin/customers?q=travels", headers=admin)).json()
    assert data["total"] == 1
    assert data["items"][0]["role"] == "employer" and data["items"][0]["phone"] == "+919876600006"


async def test_parallel_first_customer_requests_do_not_crash(client, login_as):
    import asyncio

    headers = await login_as(client, "9876600099", role="customer")
    results = await asyncio.gather(*(client.get("/customers/me", headers=headers) for _ in range(3)))
    assert [r.status_code for r in results] == [200, 200, 200]
