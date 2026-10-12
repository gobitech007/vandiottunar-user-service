import pytest

from app.services.licence import parse_licence_text
from tests.conftest import JPEG

SMART_CARD = """INDIAN UNION DRIVING LICENCE
TN38 20200001234
Issue Date 12-03-2020  Validity (NT) 11-03-2040  Validity (TR) 11-03-2023
Date of Birth 05-06-1990
AUTHORISATION TO DRIVE FOLLOWING CLASS OF VEHICLES
MCWG  LMV  TRANS"""


@pytest.mark.parametrize(
    "text,number,classes,two,four,heavy",
    [
        (SMART_CARD, "TN3820200001234", ["MCWG", "LMV", "TRANS"], True, True, False),
        ("DL No. TN-38 2O2O OO01234   COV: LMV-NT, MCWOG", "TN3820200001234", ["MCWOG", "LMVNT"], True, True, False),
        ("Licence No: KA0120150012345\nHGMV HPMV LMV MCWG", "KA0120150012345", ["MCWG", "LMV", "HGMV", "HPMV"], True, True, True),
        ("D.L.No. DL-0420110012345 MC EX50CC", "DL0420110012345", ["MCEX50CC"], True, False, False),
        ("Name: HARI SON OF RAMAN, 12 TRANSPORT NAGAR", None, [], False, False, False),
    ],
)
def test_parser(text, number, classes, two, four, heavy):
    p = parse_licence_text(text)
    assert p.licence_number == number
    assert p.classes == classes
    assert (p.two_wheeler, p.four_wheeler, p.heavy) == (two, four, heavy)


def test_parser_finds_expiry():
    assert str(parse_licence_text(SMART_CARD).valid_till) == "2040-03-11"


@pytest.mark.asyncio
async def test_parse_endpoint(client, login_as):
    headers = await login_as(client, "9876577001")
    r = await client.post("/drivers/me/licence/parse", json={"text": SMART_CARD}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["licence_number"] == "TN3820200001234" and body["four_wheeler"] and not body["heavy"]


@pytest.mark.asyncio
async def test_scan_without_server_ocr(client, login_as):
    headers = await login_as(client, "9876577002")
    assert (await client.post("/drivers/me/licence/scan", headers=headers)).status_code == 409  # no photo yet
    await client.post("/drivers/me/documents/licence_front", files={"file": ("l.jpg", JPEG, "image/jpeg")}, headers=headers)
    assert (await client.post("/drivers/me/licence/scan", headers=headers)).status_code == 501
    check = (await client.get("/drivers/me/checklist", headers=headers)).json()
    assert check["server_ocr_available"] is False and check["licence_complete"] is False


@pytest.mark.asyncio
async def test_scan_with_textract(client, login_as, monkeypatch):
    from app.core import ocr
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ocr_provider", "textract")
    monkeypatch.setattr(ocr, "_textract_text", lambda data: SMART_CARD)
    headers = await login_as(client, "9876577003")
    await client.post("/drivers/me/documents/licence_front", files={"file": ("l.jpg", JPEG, "image/jpeg")}, headers=headers)
    r = await client.post("/drivers/me/licence/scan", headers=headers)
    assert r.status_code == 200
    assert r.json()["licence_number"] == "TN3820200001234" and "MCWG" in r.json()["classes"]
    assert r.json()["raw_text"].startswith("INDIAN UNION")


@pytest.mark.asyncio
async def test_saving_licence_resets_verification(client, login_as):
    headers = await login_as(client, "9876577004")
    r = await client.put(
        "/drivers/me/licence",
        json={"licence_number": "KA0120150012345", "classes": ["hgmv", "LMV"], "source": "ocr_browser", "raw_text": "x"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["licence_classes"] == ["HGMV", "LMV"] and body["heavy_vehicle"] and not body["licence_verified"]
    assert body["licence_source"] == "ocr_browser"
