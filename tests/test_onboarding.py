import pytest

from tests.conftest import JPEG, PDF

pytestmark = pytest.mark.asyncio

PROFILE = {
    "full_name": "Murugan K",
    "preferred_language": "ta",
    "licence_number": "TN38 20200001234",
    "experience_years": 6,
    "vehicle_types": ["car_manual", "suv"],
    "availability": "full_time",
    "work_preferences": ["on_demand", "job"],
}
LOCATION = {"lat": 11.0168, "lng": 76.9558, "accuracy_m": 12, "home_pincode": "641001", "home_area": "RS Puram"}


async def complete_application(client, headers):
    assert (await client.put("/drivers/me/profile", json=PROFILE, headers=headers)).status_code == 200
    assert (await client.put("/drivers/me/location", json=LOCATION, headers=headers)).status_code == 200
    version = (await client.get("/drivers/me/checklist", headers=headers)).json()["current_consent_version"]
    assert (await client.post("/drivers/me/consent", json={"version": version}, headers=headers)).status_code == 201
    for doc in ("licence_front", "licence_back", "selfie"):
        r = await client.post(f"/drivers/me/documents/{doc}", files={"file": ("a.jpg", JPEG, "image/jpeg")}, headers=headers)
        assert r.status_code == 201, r.text
    r = await client.post("/drivers/me/documents/id_proof", files={"file": ("id.pdf", PDF, "application/pdf")}, headers=headers)
    assert r.status_code == 201


async def test_full_driver_onboarding_and_admin_approval(client, login_as):
    driver = await login_as(client, "9876543210")
    me = (await client.get("/drivers/me", headers=driver)).json()
    assert me["status"] == "draft"

    check = (await client.get("/drivers/me/checklist", headers=driver)).json()
    assert not check["ready_to_submit"]
    assert set(check["missing_documents"]) == {"licence_front", "licence_back", "id_proof", "selfie"}

    # Submitting too early is refused with the checklist
    r = await client.post("/drivers/me/submit", headers=driver)
    assert r.status_code == 409

    await complete_application(client, driver)
    check = (await client.get("/drivers/me/checklist", headers=driver)).json()
    assert check["ready_to_submit"], check

    r = await client.post("/drivers/me/submit", headers=driver)
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    assert r.json()["licence_number"] == "TN3820200001234"

    # Locked after submission
    assert (await client.put("/drivers/me/profile", json={"experience_years": 7}, headers=driver)).status_code == 409

    admin = await login_as(client, "9000000001")
    listing = (await client.get("/admin/drivers?status=submitted", headers=admin)).json()
    assert listing["total"] == 1
    driver_id = listing["items"][0]["id"]

    detail = (await client.get(f"/admin/drivers/{driver_id}", headers=admin)).json()
    assert detail["phone"] == "+919876543210"
    assert len(detail["documents"]) == 4
    assert detail["consent_version"] is not None
    assert detail["registration_lat"] == pytest.approx(11.0168)

    # Document links work without a header (signed URL) and reject tampering
    url = detail["documents"][0]["view_url"].replace("http://test", "")
    assert (await client.get(url)).status_code == 200
    assert (await client.get(url[: url.index("token=") + 6] + "bad")).status_code == 401

    # Approval requires police verification
    r = await client.post(f"/admin/drivers/{driver_id}/approve", json={"police_verified": False}, headers=admin)
    assert r.status_code == 422
    r = await client.post(
        f"/admin/drivers/{driver_id}/approve",
        json={"police_verified": True, "police_reference": "CBE-PV-1201"},
        headers=admin,
    )
    assert r.status_code == 200 and r.json()["status"] == "approved"

    me = (await client.get("/drivers/me", headers=driver)).json()
    assert me["status"] == "approved" and me["police_verified"]

    stats = (await client.get("/admin/stats", headers=admin)).json()
    assert stats["by_status"]["approved"] == 1
    assert stats["signups_by_pincode"][0] == {"pincode": "641001", "drivers": 1}


async def test_reject_then_resubmit(client, login_as):
    driver = await login_as(client, "9876543211")
    await complete_application(client, driver)
    await client.post("/drivers/me/submit", headers=driver)

    admin = await login_as(client, "9000000001")
    driver_id = (await client.get("/admin/drivers", headers=admin)).json()["items"][0]["id"]
    r = await client.post(f"/admin/drivers/{driver_id}/reject", json={"reason": "Licence photo is blurred"}, headers=admin)
    assert r.json()["status"] == "rejected"

    me = (await client.get("/drivers/me", headers=driver)).json()
    assert me["rejection_reason"] == "Licence photo is blurred"

    # Driver can fix and resubmit
    r = await client.post("/drivers/me/documents/licence_front", files={"file": ("b.jpg", JPEG, "image/jpeg")}, headers=driver)
    assert r.status_code == 201
    docs = (await client.get("/drivers/me/documents", headers=driver)).json()
    assert len(docs) == 4  # replaced, not duplicated
    r = await client.post("/drivers/me/submit", headers=driver)
    assert r.json()["status"] == "submitted" and r.json()["rejection_reason"] is None


async def test_upload_validation(client, login_as):
    driver = await login_as(client, "9876543212")
    # Claims to be a JPEG but isn't
    r = await client.post("/drivers/me/documents/licence_front", files={"file": ("x.jpg", b"not an image", "image/jpeg")}, headers=driver)
    assert r.status_code == 415
    r = await client.post("/drivers/me/documents/selfie", files={"file": ("s.pdf", PDF, "application/pdf")}, headers=driver)
    assert r.status_code == 415
    big = b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024 + 1)
    r = await client.post("/drivers/me/documents/licence_back", files={"file": ("big.jpg", big, "image/jpeg")}, headers=driver)
    assert r.status_code == 413


async def test_profile_validation(client, login_as):
    driver = await login_as(client, "9876543213")
    assert (await client.put("/drivers/me/profile", json={"licence_number": "12345678"}, headers=driver)).status_code == 422
    assert (await client.put("/drivers/me/profile", json={"vehicle_types": ["rocket"]}, headers=driver)).status_code == 422
    assert (await client.put("/drivers/me/location", json={**LOCATION, "home_pincode": "041001"}, headers=driver)).status_code == 422
    assert (await client.post("/drivers/me/consent", json={"version": "old"}, headers=driver)).status_code == 400


async def test_nearby_search(client, login_as):
    driver = await login_as(client, "9876543214")
    await complete_application(client, driver)
    await client.post("/drivers/me/submit", headers=driver)
    admin = await login_as(client, "9000000001")
    driver_id = (await client.get("/admin/drivers", headers=admin)).json()["items"][0]["id"]
    await client.post(f"/admin/drivers/{driver_id}/approve", json={"police_verified": True}, headers=admin)

    # Gandhipuram is ~3 km from RS Puram
    near = (await client.get("/admin/drivers/nearby?lat=11.0183&lng=76.9725&radius_km=5", headers=admin)).json()
    assert len(near) == 1 and near[0]["within_service_area"] and 1 < near[0]["distance_km"] < 3
    # Chennai is far away
    far = (await client.get("/admin/drivers/nearby?lat=13.0827&lng=80.2707&radius_km=50", headers=admin)).json()
    assert far == []


async def test_parallel_first_requests_do_not_crash(client, login_as):
    # The apps call /drivers/me and /drivers/me/checklist at the same time for a brand-new driver
    import asyncio

    driver = await login_as(client, "9876543299")
    results = await asyncio.gather(
        client.get("/drivers/me", headers=driver),
        client.get("/drivers/me/checklist", headers=driver),
        client.get("/drivers/me/documents", headers=driver),
    )
    assert [r.status_code for r in results] == [200, 200, 200]


async def test_unexpected_error_is_json_with_cors(client, monkeypatch):
    from app.routers import drivers

    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(drivers, "get_or_create_profile", boom)
    code = (await client.post("/auth/otp/request", json={"phone": "9876543298"})).json()["dev_code"]
    token = (await client.post("/auth/otp/verify", json={"phone": "9876543298", "code": code})).json()["access_token"]
    r = await client.get(
        "/drivers/me", headers={"Authorization": f"Bearer {token}", "Origin": "http://localhost:5173"}
    )
    assert r.status_code == 500
    assert r.json()["detail"].startswith("Something went wrong")
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
