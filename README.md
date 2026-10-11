# Vandi Ottunar — User Service

FastAPI service for accounts and **driver onboarding**: OTP login, driver profile, location capture, document upload, privacy consent, and admin approval with police verification.

Part of the Vandi Ottunar platform:

| Repo | Purpose |
|---|---|
| `vandiottunar-user-service` | **This repo** — auth, drivers, admin review |
| `vandiottunar-frontend` | Web admin panel + Android driver app |
| `vandiottunar-order-service` | Bookings and job posts (next phase) |
| `vandiottunar-payment-service` | Payments and driver payouts (next phase) |
| `vandiottunar-report-service` | Reports and analytics (next phase) |

## Driver onboarding flow

```
OTP login → accept privacy notice → profile → location (GPS + home pincode + service radius)
→ upload licence (front/back), ID proof, selfie → submit → admin review
→ police verification → approved / rejected (driver fixes and resubmits)
```

A driver can register from anywhere: the phone's GPS fix is saved as the **registration location**, and the driver separately confirms the **home pincode / work area and service radius** (they often differ). Both models are supported: `work_preferences` holds `on_demand` (trips) and/or `job` (placements).

## Run locally

```bash
cp .env.example .env            # set ADMIN_PHONES to your number
docker compose up --build       # Postgres + API on http://localhost:8000
```

Interactive API docs: http://localhost:8000/docs

Without Docker:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

In development (`SMS_PROVIDER=console`) the OTP is printed in the server log and returned as `dev_code`, so you can log in without SMS.

## API

| Method | Path | Who | What |
|---|---|---|---|
| POST | `/auth/otp/request` | anyone | Send OTP (30s resend wait, 5 per hour) |
| POST | `/auth/otp/verify` | anyone | Verify OTP → JWT. New users get the requested role (`driver`, `customer`, `employer`); `ADMIN_PHONES` become `admin` |
| GET | `/auth/me` | logged in | Current user |
| GET | `/drivers/me` | driver | Profile (created as draft on first call) |
| PUT | `/drivers/me/profile` | driver | Name, licence no., experience, vehicle types, availability, work preferences |
| PUT | `/drivers/me/location` | driver | GPS fix + home pincode/area + service radius |
| POST | `/drivers/me/consent` | driver | Accept the current privacy notice version |
| POST | `/drivers/me/documents/{type}` | driver | Upload `licence_front`, `licence_back`, `id_proof`, `address_proof` (optional), `selfie` |
| GET | `/drivers/me/checklist` | driver | What's still missing before submit |
| POST | `/drivers/me/submit` | driver | Submit for review |
| GET | `/admin/drivers?status=&q=` | admin | List / search applications |
| GET | `/admin/drivers/{id}` | admin | Full detail with short-lived document links |
| POST | `/admin/drivers/{id}/approve` | admin | Approve — **requires police verification** |
| POST | `/admin/drivers/{id}/reject` | admin | Reject with a reason the driver sees |
| POST | `/admin/drivers/{id}/suspend` | admin | Suspend an approved driver |
| GET | `/admin/drivers/nearby?lat=&lng=&radius_km=` | admin | Approved drivers near a point |
| GET | `/admin/stats` | admin | Counts by status + signups by pincode |

## Security notes

- OTPs are stored as HMAC hashes, expire in 5 minutes, allow 5 attempts, and only the newest code is valid.
- Uploads are checked by size (5 MB) and by file signature, not just the declared type.
- Documents are never public: admins get links signed for 5 minutes; in S3 mode they are presigned URLs to a private, encrypted bucket.
- Consent records store version, time, IP and user agent (DPDP Act evidence).
- Every admin decision is written to `review_events`.
- In production the service refuses to start with a weak `JWT_SECRET` or the console SMS provider.

## Tests

```bash
pytest                                              # SQLite
TEST_DATABASE_URL=postgresql+asyncpg://... pytest   # PostgreSQL
```

## Going to production (AWS ap-south-1)

- RDS PostgreSQL, a private S3 bucket (`STORAGE_BACKEND=s3`), the API on ECS/App Runner or EC2 behind HTTPS.
- Register a DLT sender ID and OTP template, then set `SMS_PROVIDER=msg91` (check MSG91's current API docs).
- Set `ENVIRONMENT=production`, a long random `JWT_SECRET`, and `CORS_ORIGINS` to your real domains.
