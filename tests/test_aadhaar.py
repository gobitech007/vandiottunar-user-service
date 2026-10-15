import pytest

from app.services.aadhaar import find_aadhaar, is_valid_aadhaar, mask
from app.services.licence import parse_licence_text

VALID = "234567890124"
AADHAAR_CARD = f"""Government of India
MURUGAN K
DOB: 05/06/1990  MALE
{VALID[:4]} {VALID[4:8]} {VALID[8:]}
VID : 9134 5678 9012 3456
Aadhaar - Aam Aadmi ka Adhikar"""


def test_checks():
    assert is_valid_aadhaar(VALID)
    assert not is_valid_aadhaar("234567890123")  # wrong check digit
    assert not is_valid_aadhaar("134567890124")  # can't start with 1
    assert mask(VALID) == "XXXX XXXX 0124"


def test_find_in_card_text():
    assert find_aadhaar(AADHAAR_CARD) == VALID
    assert find_aadhaar("VID : 9134 5678 9012 3456") is None  # 16-digit virtual ID is not the number
    assert find_aadhaar(f"No. {VALID[:4]} {VALID[4:8].replace('8', 'B')} {VALID[8:].replace('0', 'O')}") == VALID  # OCR mix-ups
    assert find_aadhaar("Phone 9876543210") is None


@pytest.mark.asyncio
async def test_parse_and_save_keeps_only_last4(client, login_as):
    headers = await login_as(client, "9876588001")
    r = await client.post("/drivers/me/aadhaar/parse", json={"text": AADHAAR_CARD}, headers=headers)
    assert r.status_code == 200
    assert r.json() == {"aadhaar_number": VALID, "masked": "XXXX XXXX 0124", "wording_found": True}

    bad = await client.put("/drivers/me/aadhaar", json={"aadhaar_number": "2345 6789 0123"}, headers=headers)
    assert bad.status_code == 422

    r = await client.put("/drivers/me/aadhaar", json={"aadhaar_number": "2345-6789-0124", "source": "ocr_browser"}, headers=headers)
    assert r.status_code == 200 and r.json()["aadhaar_last4"] == "0124"
    assert VALID not in r.text
    check = (await client.get("/drivers/me/checklist", headers=headers)).json()
    assert check["aadhaar_captured"] is True


def test_licence_photo_check():
    real = parse_licence_text("INDIAN UNION DRIVING LICENCE\nTN38 20200001234\nValid Till 11-03-2040\nCOV MCWG LMV LMV-TR")
    assert real.wording_found and real.looks_like_licence
    assert real.classes == ["MCWG", "LMV", "LMVTR"]
    # A photo of something else
    other = parse_licence_text("ELECTRICITY BILL Consumer No 0412345678 Due 12-10-2026")
    assert not other.looks_like_licence


@pytest.mark.asyncio
async def test_expired_licence(client, login_as):
    headers = await login_as(client, "9876588002")
    r = await client.post(
        "/drivers/me/licence/parse", json={"text": "DRIVING LICENCE TN38 20100001234 Valid Till 01-01-2020 LMV"}, headers=headers
    )
    assert r.json()["expired"] is True and r.json()["looks_like_licence"] is True
    r = await client.put(
        "/drivers/me/licence",
        json={"licence_number": "TN3820100001234", "classes": ["LMV"], "valid_till": "2020-01-01"},
        headers=headers,
    )
    assert r.status_code == 422 and "expired" in r.text
