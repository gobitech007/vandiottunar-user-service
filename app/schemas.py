import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import DocumentType, DriverStatus, Role

_PHONE_RE = re.compile(r"^[6-9]\d{9}$")

VehicleType = Literal["car_manual", "car_automatic", "suv", "van", "light_commercial", "heavy_vehicle"]
Availability = Literal["full_time", "part_time", "weekends"]
WorkPreference = Literal["on_demand", "job"]


def normalize_indian_phone(value: str) -> str:
    digits = re.sub(r"[\s\-()]", "", value)
    if digits.startswith("+91"):
        digits = digits[3:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if not _PHONE_RE.match(digits):
        raise ValueError("Enter a valid 10-digit Indian mobile number")
    return f"+91{digits}"


class PhoneIn(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_indian_phone(v)


class OtpRequestOut(BaseModel):
    message: str
    resend_after_seconds: int
    dev_code: str | None = None  # only returned in development with the console SMS provider


class OtpVerifyIn(PhoneIn):
    code: str = Field(min_length=4, max_length=8, pattern=r"^\d+$")
    role: Literal["driver", "customer", "employer"] = "driver"


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: Role
    is_new_user: bool


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    phone: str
    role: Role
    created_at: datetime


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    preferred_language: Literal["ta", "en"] | None = None
    licence_number: str | None = Field(default=None, min_length=8, max_length=32)
    experience_years: int | None = Field(default=None, ge=0, le=60)
    vehicle_types: list[VehicleType] | None = Field(default=None, max_length=6)
    availability: Availability | None = None
    work_preferences: list[WorkPreference] | None = Field(default=None, max_length=2)
    expected_pay_note: str | None = Field(default=None, max_length=120)

    @field_validator("licence_number")
    @classmethod
    def _licence(cls, v: str | None) -> str | None:
        if v is None:
            return v
        cleaned = re.sub(r"[\s\-]", "", v).upper()
        if not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]{4,}$", cleaned):
            raise ValueError("Licence number should look like TN3820200001234")
        return cleaned


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0)
    home_pincode: str = Field(pattern=r"^[1-9]\d{5}$")
    home_area: str | None = Field(default=None, max_length=120)
    home_lat: float | None = Field(default=None, ge=-90, le=90)
    home_lng: float | None = Field(default=None, ge=-180, le=180)
    service_radius_km: int = Field(default=10, ge=2, le=100)


class ConsentIn(BaseModel):
    version: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    doc_type: DocumentType
    content_type: str
    size_bytes: int
    uploaded_at: datetime


class AdminDocumentOut(DocumentOut):
    view_url: str


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    full_name: str | None
    preferred_language: str
    licence_number: str | None
    experience_years: int | None
    vehicle_types: list[str]
    availability: str | None
    work_preferences: list[str]
    expected_pay_note: str | None
    home_pincode: str | None
    home_area: str | None
    home_lat: float | None
    home_lng: float | None
    service_radius_km: int
    registration_lat: float | None
    registration_lng: float | None
    location_captured_at: datetime | None
    status: DriverStatus
    rejection_reason: str | None
    police_verified: bool
    submitted_at: datetime | None
    reviewed_at: datetime | None
    created_at: datetime


class ChecklistOut(BaseModel):
    profile_complete: bool
    location_captured: bool
    consent_accepted: bool
    missing_documents: list[DocumentType]
    missing_fields: list[str]
    ready_to_submit: bool
    current_consent_version: str


class AdminDriverSummary(BaseModel):
    id: str
    full_name: str | None
    phone: str
    status: DriverStatus
    home_pincode: str | None
    home_area: str | None
    experience_years: int | None
    work_preferences: list[str]
    police_verified: bool
    submitted_at: datetime | None
    created_at: datetime


class AdminDriverDetail(ProfileOut):
    phone: str
    police_reference: str | None
    registration_accuracy_m: float | None
    documents: list[AdminDocumentOut]
    consent_version: str | None
    consent_accepted_at: datetime | None


class DriverList(BaseModel):
    items: list[AdminDriverSummary]
    total: int


class ApproveIn(BaseModel):
    police_verified: bool
    police_reference: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class NearbyDriver(BaseModel):
    id: str
    full_name: str | None
    phone: str
    distance_km: float
    within_service_area: bool
    vehicle_types: list[str]
    work_preferences: list[str]


class StatsOut(BaseModel):
    by_status: dict[str, int]
    signups_by_pincode: list[dict]
