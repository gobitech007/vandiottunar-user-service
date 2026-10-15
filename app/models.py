import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.security import utcnow
from app.db import Base
from app.services.licence import capabilities


def new_id() -> str:
    return str(uuid.uuid4())


def str_enum(e: type[enum.Enum]) -> Enum:
    # Stored as VARCHAR + CHECK, so adding values later is a simple migration
    return Enum(e, native_enum=False, values_callable=lambda x: [m.value for m in x], length=32)


class Role(str, enum.Enum):
    driver = "driver"
    customer = "customer"  # car owner booking a driver (on-demand model)
    employer = "employer"  # fleet / household posting driver jobs (recruitment model)
    admin = "admin"


class DriverStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class DocumentType(str, enum.Enum):
    licence_front = "licence_front"
    licence_back = "licence_back"
    id_proof = "id_proof"
    address_proof = "address_proof"
    selfie = "selfie"


REQUIRED_DOCUMENTS = (
    DocumentType.licence_front,
    DocumentType.licence_back,
    DocumentType.id_proof,
    DocumentType.selfie,
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    role: Mapped[Role] = mapped_column(str_enum(Role), default=Role.driver)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    driver_profile: Mapped["DriverProfile | None"] = relationship(back_populates="user", uselist=False)


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    phone: Mapped[str] = mapped_column(String(16), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class DriverProfile(Base):
    __tablename__ = "driver_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    # Personal / work details
    full_name: Mapped[str | None] = mapped_column(String(120))
    preferred_language: Mapped[str] = mapped_column(String(8), default="ta")
    licence_number: Mapped[str | None] = mapped_column(String(32))
    # Class-of-vehicle codes from the licence (e.g. MCWG, LMV, HGMV); see app/services/licence.py
    licence_classes: Mapped[list[str]] = mapped_column(JSON, default=list)
    licence_valid_till: Mapped[date | None] = mapped_column(Date)
    licence_source: Mapped[str | None] = mapped_column(String(16))  # manual | ocr_browser | ocr_server | ocr_device
    licence_raw_text: Mapped[str | None] = mapped_column(Text)  # OCR text kept for the admin to compare
    licence_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # admin checked classes vs photo
    # Aadhaar: only the last 4 digits are kept (masked as XXXX XXXX 1234)
    aadhaar_last4: Mapped[str | None] = mapped_column(String(4))
    aadhaar_source: Mapped[str | None] = mapped_column(String(16))  # manual | ocr_browser | ocr_server | ocr_device
    experience_years: Mapped[int | None] = mapped_column(Integer)
    vehicle_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    availability: Mapped[str | None] = mapped_column(String(16))
    # Both business models: "on_demand" trips and/or "job" placements
    work_preferences: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_pay_note: Mapped[str | None] = mapped_column(String(120))

    # Where they want to work (may differ from where they registered)
    home_pincode: Mapped[str | None] = mapped_column(String(6), index=True)
    home_area: Mapped[str | None] = mapped_column(String(120))
    home_lat: Mapped[float | None] = mapped_column(Float)
    home_lng: Mapped[float | None] = mapped_column(Float)
    service_radius_km: Mapped[int] = mapped_column(Integer, default=10)

    # GPS fix captured on the phone at registration time
    registration_lat: Mapped[float | None] = mapped_column(Float)
    registration_lng: Mapped[float | None] = mapped_column(Float)
    registration_accuracy_m: Mapped[float | None] = mapped_column(Float)
    location_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Review
    status: Mapped[DriverStatus] = mapped_column(str_enum(DriverStatus), default=DriverStatus.draft, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    police_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    police_reference: Mapped[str | None] = mapped_column(String(64))
    police_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(36))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="driver_profile")

    # What the licence allows, derived from its class codes
    @property
    def two_wheeler(self) -> bool:
        return capabilities(self.licence_classes or [])["two_wheeler"]

    @property
    def four_wheeler(self) -> bool:
        return capabilities(self.licence_classes or [])["four_wheeler"]

    @property
    def heavy_vehicle(self) -> bool:
        return capabilities(self.licence_classes or [])["heavy"]

    documents: Mapped[list["DriverDocument"]] = relationship(
        back_populates="driver", cascade="all, delete-orphan", order_by="DriverDocument.doc_type"
    )


class DriverDocument(Base):
    __tablename__ = "driver_documents"
    __table_args__ = (UniqueConstraint("driver_id", "doc_type", name="uq_driver_doc_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    driver_id: Mapped[str] = mapped_column(ForeignKey("driver_profiles.id", ondelete="CASCADE"), index=True)
    doc_type: Mapped[DocumentType] = mapped_column(str_enum(DocumentType))
    storage_key: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    driver: Mapped[DriverProfile] = relationship(back_populates="documents")


class CustomerProfile(Base):
    """A car owner booking drivers (role=customer) or a business hiring drivers (role=employer)."""

    __tablename__ = "customer_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254))
    preferred_language: Mapped[str] = mapped_column(String(8), default="ta")
    company_name: Mapped[str | None] = mapped_column(String(160))  # employers only
    home_pincode: Mapped[str | None] = mapped_column(String(6), index=True)
    home_area: Mapped[str | None] = mapped_column(String(120))
    # What they want: "on_demand" (hourly/daily/outstation driver) and/or "job" (permanent driver)
    needs: Mapped[list[str]] = mapped_column(JSON, default=list)
    vehicle_note: Mapped[str | None] = mapped_column(String(120))  # e.g. "Innova, automatic"
    car_number: Mapped[str | None] = mapped_column(String(16))  # registration number, e.g. TN37AB1234
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship()


class Consent(Base):
    """Proof of consent to the driver notice (DPDP Act)."""

    __tablename__ = "consents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(32))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))


class ReviewEvent(Base):
    """Audit trail of admin decisions — useful for disputes."""

    __tablename__ = "review_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    driver_id: Mapped[str] = mapped_column(ForeignKey("driver_profiles.id", ondelete="CASCADE"), index=True)
    admin_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
