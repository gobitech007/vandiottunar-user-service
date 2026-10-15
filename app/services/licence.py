"""Read an Indian driving licence from OCR text.

The same parser is used for every OCR source (the browser's Tesseract, AWS Textract on the server,
or a phone's text recogniser) so the rules live in one place. OCR output is noisy, so everything
here is a best guess that the driver confirms and an admin verifies against the photo.
"""

import re
from dataclasses import dataclass, field
from datetime import date

# Class of vehicle (COV) codes printed on Indian licences, grouped by what they allow.
TWO_WHEELER = {"MCWG", "MCWOG", "MC50CC", "MCEX50CC", "FVG", "MCYCL"}
FOUR_WHEELER = {"LMV", "LMVNT", "LMVTR", "LMVCAB", "LMVTAXI", "LMVINVCRG", "3WNT", "3WT", "LMVAR"}
HEAVY = {"HMV", "HGMV", "HPMV", "HTV", "HTRAILER", "HGV", "HPV", "MGV", "MPMV", "MMV", "TRAILR"}
TRANSPORT = {"TRANS"}  # commercial (transport) endorsement; heavy only if a heavy class is also listed

ALL_CLASSES = TWO_WHEELER | FOUR_WHEELER | HEAVY | TRANSPORT

# Display form for each normalised code
DISPLAY = {
    "MCWG": "MCWG",
    "MCWOG": "MCWOG",
    "MC50CC": "MC 50CC",
    "MCEX50CC": "MC EX50CC",
    "FVG": "FVG",
    "MCYCL": "M/CYCL",
    "LMV": "LMV",
    "LMVNT": "LMV-NT",
    "LMVTR": "LMV-TR",
    "LMVCAB": "LMV-CAB",
    "LMVTAXI": "LMV-TAXI",
    "LMVINVCRG": "LMV-INVCRG",
    "LMVAR": "LMV-AR",
    "3WNT": "3W-NT",
    "3WT": "3W-T",
    "HMV": "HMV",
    "HGMV": "HGMV",
    "HPMV": "HPMV",
    "HTV": "HTV",
    "HTRAILER": "HTRAILER",
    "HGV": "HGV",
    "HPV": "HPV",
    "MGV": "MGV",
    "MPMV": "MPMV",
    "MMV": "MMV",
    "TRAILR": "TRAILR",
    "TRANS": "TRANS",
}

# Licence number: state (2 letters) + RTO (2 digits) + year of issue (4 digits) + serial (7 digits)
_DL_STRICT = re.compile(r"\b([A-Z]{2})[\s\-./]?(\d{2})[\s\-./]?((?:19|20)\d{2})[\s\-./]?(\d{7})\b")
# Older licences: state + RTO + a longer number without a year
_DL_LOOSE = re.compile(r"\b([A-Z]{2})[\s\-./]?(\d{2})[\s\-./]?([0-9]{6,13})\b")
_DL_LABELLED = re.compile(r"(?:DL\s*NO|D\.?\s*L\.?\s*NO|LICEN[CS]E\s*NO)[\s.:\-]*([A-Z0-9][A-Z0-9\s\-/]{9,20})")

_DATE = re.compile(r"\b(\d{2})[\-/.](\d{2})[\-/.]((?:19|20)\d{2})\b")
_VALID_LABEL = re.compile(r"VALID(?:ITY)?\s*(?:TILL|UPTO|UP\s*TO|\(?NT\)?|\(?TR\)?)?", re.I)

STATE_CODES = {
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA", "GJ", "HP", "HR", "JH", "JK", "KA", "KL",
    "LA", "LD", "MH", "ML", "MN", "MP", "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK",
    "UP", "WB",
}


# Wording printed on Indian licences (next to the national emblem). Compared with letters only, so OCR
# spacing and punctuation don't matter.
LICENCE_WORDING = (
    "DRIVINGLICENCE",
    "DRIVINGLICENSE",
    "INDIANUNION",
    "UNIONOFINDIA",
    "TRANSPORTDEPARTMENT",
    "TRANSPORTDEPT",
    "MOTORVEHICLESDEPARTMENT",
    "SATYAMEVAJAYATE",
    "SATYAMEVJAYATE",
    "PARIVAHAN",
)


@dataclass
class ParsedLicence:
    licence_number: str | None = None
    classes: list[str] = field(default_factory=list)
    valid_till: date | None = None
    wording_found: bool = False

    @property
    def looks_like_licence(self) -> bool:
        """The photo reads like a driving licence: official wording plus a number, or a number with classes and a date."""
        if not self.licence_number:
            return False
        return self.wording_found or bool(self.classes and self.valid_till)

    def expired(self, today: date) -> bool:
        return self.valid_till is not None and self.valid_till < today

    @property
    def two_wheeler(self) -> bool:
        return bool(set(self.classes) & TWO_WHEELER)

    @property
    def four_wheeler(self) -> bool:
        return bool(set(self.classes) & (FOUR_WHEELER | HEAVY))

    @property
    def heavy(self) -> bool:
        return bool(set(self.classes) & HEAVY)


def normalise_class(raw: str) -> str | None:
    code = re.sub(r"[^A-Z0-9]", "", raw.upper())
    code = {"MCWITHGEAR": "MCWG", "MCWITHOUTGEAR": "MCWOG", "LMVNONTRANSPORT": "LMVNT"}.get(
        code, code
    )
    return code if code in ALL_CLASSES else None


def capabilities(classes: list[str]) -> dict[str, bool]:
    parsed = ParsedLicence(classes=classes)
    return {"two_wheeler": parsed.two_wheeler, "four_wheeler": parsed.four_wheeler, "heavy": parsed.heavy}


def _digits_fix(s: str) -> str:
    # Common OCR confusions inside the numeric part of a licence number
    return s.translate(str.maketrans({"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"}))


def _find_number(text: str) -> str | None:
    upper = text.upper()
    candidates: list[str] = []
    m = _DL_LABELLED.search(upper)
    if m:
        candidates.append(m.group(1))
    candidates.append(upper)
    for chunk in candidates:
        # Repair digits that follow a state code before matching
        repaired = re.sub(
            r"\b([A-Z]{2})([\s\-./]?)([0-9OIDQLSBZ][0-9OIDQLSBZ\s\-./]{8,20})",
            lambda mm: mm.group(1) + mm.group(2) + _digits_fix(mm.group(3)),
            chunk,
        )
        for pattern in (_DL_STRICT, _DL_LOOSE):
            for match in pattern.finditer(repaired):
                if match.group(1) in STATE_CODES:
                    return "".join(match.groups())
    return None


def _find_classes(text: str) -> list[str]:
    upper = text.upper()
    found: set[str] = set()
    # Codes may be one word ("LMV-NT") or split by OCR ("MC EX50CC", "LMV NT"), so try 1-3 word windows
    words = [w for w in re.split(r"[\s,;|:()]+", upper) if w]
    for i in range(len(words)):
        for size in (3, 2, 1):
            code = normalise_class("".join(words[i : i + size]))
            if code:
                found.add(code)
                break
    if "WITHOUT GEAR" in upper:
        found.add("MCWOG")
    elif "WITH GEAR" in upper:
        found.add("MCWG")
    if "M/CYCL" in upper or "MCYCL" in upper.replace(" ", ""):
        found.add("MCWG")
    found.discard("MCYCL")
    return sorted(found, key=lambda c: (c not in TWO_WHEELER, c not in FOUR_WHEELER, c))


def _find_valid_till(text: str) -> date | None:
    dates: list[tuple[int, date]] = []
    for m in _DATE.finditer(text):
        try:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
        before = text[max(0, m.start() - 30) : m.start()]
        dates.append((1 if _VALID_LABEL.search(before) else 0, d))
    if not dates:
        return None
    labelled = [d for score, d in dates if score]
    # A licence's expiry is the latest date printed on it
    return max(labelled or [d for _, d in dates])


def has_licence_wording(text: str) -> bool:
    letters = re.sub(r"[^A-Z]", "", (text or "").upper())
    return any(w in letters for w in LICENCE_WORDING)


def parse_licence_text(text: str) -> ParsedLicence:
    text = text or ""
    return ParsedLicence(
        licence_number=_find_number(text),
        classes=_find_classes(text),
        valid_till=_find_valid_till(text),
        wording_found=has_licence_wording(text),
    )
