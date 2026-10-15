"""Find an Aadhaar number in OCR text from an ID photo.

Only the last 4 digits are ever stored (UIDAI rules: services that aren't authorised to keep Aadhaar
numbers must mask them). The full number is used just long enough to check it is a real Aadhaar number
(12 digits, not starting with 0 or 1, valid Verhoeff check digit).
"""

import re

# Verhoeff tables
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]

AADHAAR_WORDING = ("AADHAAR", "AADHAR", "UNIQUEIDENTIFICATIONAUTHORITY", "UIDAI", "GOVERNMENTOFINDIA", "MERAAADHAAR")

# 12 digits, usually printed as 4-4-4. Not part of a longer run (the 16-digit Virtual ID).
_NUMBER = re.compile(r"(?<![0-9OIlSB])([2-9OSB][0-9OIlSB]{3})[ \-]?([0-9OIlSB]{4})[ \-]?([0-9OIlSB]{4})(?![ \-]?[0-9OIlSB]{2})")
_FIX = str.maketrans({"O": "0", "I": "1", "l": "1", "S": "5", "B": "8"})


def verhoeff_ok(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def is_valid_aadhaar(number: str) -> bool:
    return bool(re.fullmatch(r"[2-9]\d{11}", number)) and verhoeff_ok(number)


def clean(value: str) -> str:
    return re.sub(r"[\s\-]", "", value or "")


def mask(number: str) -> str:
    return f"XXXX XXXX {number[-4:]}"


def has_aadhaar_wording(text: str) -> bool:
    letters = re.sub(r"[^A-Z]", "", (text or "").upper())
    return any(w in letters for w in AADHAAR_WORDING)


def find_aadhaar(text: str) -> str | None:
    """The first 12-digit number in the text that passes the Aadhaar checks."""
    for m in _NUMBER.finditer(text or ""):
        number = "".join(m.groups()).translate(_FIX)
        if is_valid_aadhaar(number):
            return number
    return None
