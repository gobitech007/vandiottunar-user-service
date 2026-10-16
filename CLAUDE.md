# CLAUDE.md: vandiottunar-user-service

Accounts and people: OTP login, JWTs, driver onboarding and admin approval, customer profiles.
FastAPI · async SQLAlchemy 2 · Alembic (async, `render_as_batch` for SQLite) · pydantic-settings · PyJWT · port **8000** · DB `vandi_users`.

## Layout

```
app/
  main.py            FastAPI app, JSON 500 middleware (inside CORS so errors keep CORS headers)
  core/config.py     Settings from .env (JWT_SECRET, ADMIN_PHONES, SMS_PROVIDER, STORAGE_BACKEND, OCR_PROVIDER, SERVICE_TOKEN…)
  core/security.py   JWT create/verify, OTP hashing (HMAC), file-view tokens
  core/sms.py        console (dev: OTP in log + returned as dev_code) | msg91
  core/storage.py    local ./uploads | private S3
  core/ocr.py        none | textract (AWS Textract) for licence/Aadhaar photos
  models.py          User, OtpCode, DriverProfile, DriverDocument, Consent, CustomerProfile
  routers/auth.py    /auth/otp/request, /auth/otp/verify (role + intent=register|login), /auth/me
  routers/drivers.py /drivers/me/* onboarding: profile, licence parse/scan/save, aadhaar parse/scan/save, location, consent, documents, checklist, submit
  routers/customers.py /customers/me
  routers/admin.py   /admin/drivers (list, detail, approve/reject/suspend, nearby), /admin/customers, /admin/stats, document files
  routers/internal.py /internal/drivers, /internal/users/{id}  (X-Service-Token; used by order-service)
  services/licence.py  Indian licence parser: number, validity, COV classes (MCWG/LMV/LMV-TR/HGMV…), wording check
  services/aadhaar.py  Aadhaar finder + Verhoeff check; only last 4 digits are ever stored
  services/onboarding.py checklist (what's missing before submit), get_or_create with IntegrityError race handling
tests/               pytest on SQLite (conftest sets env before importing the app)
```

## Domain rules that matter

- A phone number has one role. `intent=login` never creates accounts; `role=admin` only for numbers in `ADMIN_PHONES`.
- Driver submit needs: profile fields, licence number + classes (not expired), Aadhaar last 4, location (GPS + pincode), current consent version, documents `licence_front`, `licence_back`, `id_proof`, `selfie`.
- Admin approve needs police verification ticked **and** licence checked (`licence_verified`), and refuses expired licences.
- Licence classes map to capabilities: two_wheeler (MCWG…), four_wheeler (LMV… and heavy), heavy (HMV/HGMV/HPMV…). The order-service matches on these.
- Expiry dates use India's date (`services/timeutil.today_ist`, fixed +05:30, no tzdata needed on Windows).
- Uploads: JPG/PNG/WEBP/PDF checked by magic bytes, ≤ `MAX_UPLOAD_MB`.

## Commands

```powershell
python -m uvicorn app.main:app --reload --port 8000
python -m alembic upgrade head
python -m alembic revision --autogenerate -m "what changed"; python -m alembic check
python -m pytest -q
```

## Feature log

- Driver onboarding (OTP, consent, profile, location, documents), admin review, customer registration.
- Login after registration with the same OTP; role-safe login.
- Licence OCR (browser Tesseract or AWS Textract) → parser; classes and validity; admin licence check.
- Licence photo check (official wording), expiry shown and enforced; Aadhaar number read from the ID photo, Verhoeff-checked, last 4 stored (required to submit).
- `/internal` API for the order-service.
- Customers accept the booking & cancellation policy (versioned, `accept_policy_version`); profile isn't complete without it; `/internal/users` reports `policy_accepted`.

## Vandi Ottunar: the whole project

**Vandi Ottunar** (வண்டி ஓட்டுநர், "vehicle driver") is a driver-hiring platform for Tamil Nadu, starting in Coimbatore.
Customers (car owners) and businesses book verified drivers by the hour/day/outstation trip or hire permanent drivers.
Drivers register from their phone, upload their licence and Aadhaar, get police-verified and approved, then receive bookings.
Domain: vandiottunar.in. Owner: Gobinath (gobitech007). Brand: green `#0E3B2E`, mustard `#F2B705`, cream `#F7F1E3`.
**Tamil first, English second**: every user-facing string exists in both languages.

### Repositories (all under github.com/gobitech007, checked out side by side)

| Repo | What | Port | Database |
|---|---|---|---|
| `vandiottunar-user-service` | Accounts, OTP login (JWT), driver onboarding (profile, licence OCR, Aadhaar last-4, documents, consent), customer profiles, admin approval | 8000 | `vandi_users` |
| `vandiottunar-order-service` | Bookings, driver matching/assignment, ₹1 confirmation gate, trip start/end codes, live GPS tracking, WhatsApp chat relay | 8001 | `vandi_orders` |
| `vandiottunar-payment-service` | ₹1 booking confirmation via Razorpay Payment Links (mock checkout in dev) | 8002 | `vandi_payments` |
| `vandiottunar-report-service` | Planned: reports/analytics for admins | 8003 | `vandi_reports` |
| `vandiottunar-frontend` | `web/` React site (public + `/admin`) on 5173; `mobile/` Expo Android app (driver **and** customer) | 5173 | — |

### How the services talk

- **Login**: only the user-service issues JWTs (HS256). Every service verifies them with the **same `JWT_SECRET`**. Claims: `sub` (user id), `role` (`driver` | `customer` | `employer` | `admin`), `typ=access`.
- **Service to service**: `X-Service-Token: <SERVICE_TOKEN>` (same value in every `.env`). Each service exposes `/internal/...` only with that header.
  - order-service → user-service: `GET /internal/drivers?status=approved`, `GET /internal/users/{id}`
  - payment-service → order-service: `GET /internal/bookings/{id}` (incl. `fee_paise`, `cancel_fee_paise`), `POST /internal/bookings/{id}/paid` (₹1 confirmation), `POST /internal/bookings/{id}/cancel-paid` (cancellation fee paid → cancel)
- **Booking lifecycle** (order-service `BookingStatus`): `pending` → `assigned` (admin manual/auto) → *customer pays ₹1* (`payment_status` `unpaid` → `paid`/`waived`) → `in_progress` (driver enters customer's **start code**) → `completed` (driver enters **end code**), or `cancelled`.
- **Cancellation fee**: customer cancellations cost `CANCELLATION_FEE_PAISE` (₹49) once a driver is assigned (`CANCELLATION_FEE_APPLIES=assigned|always|never`). The customer pays it through the payment-service (`POST /payments/booking/{id}/cancel`), which then cancels the booking. Admin cancellations are free. Public `GET /bookings/policy` (order-service) gives the fee amounts shown in the policy text.
- **Driver fare** (order-service `services/fares.py`): trips cost `HOURLY_RATE_PAISE` ₹150/h and `DAILY_RATE_PAISE` ₹1000 per `DAILY_HOURS` 8 h day; hours beyond full days are hourly but never more than one more day (7 h = ₹1000); time rounds up to whole hours, minimum 1. A new customer's first booking (no earlier non-cancelled booking) gets `NEW_CUSTOMER_DISCOUNT_PCT` 10% off. Rates and discount are copied onto the booking. Bookings return `rates` and `fare` (`basis` planned = booked times, actual = start to end code); no end time → `rates` only; permanent jobs aren't priced. Customers see the fare in the ₹1 confirm box before paying (web + app). Fare is shown, not collected online.
- **Booking & cancellation policy**: customers accept it at registration (user-service `CustomerProfile.policy_version`, `CUSTOMER_POLICY_VERSION`; bump it when the text changes and customers must accept again). The order-service refuses bookings from customers who haven't accepted it. Policy text lives in web `i18n.tsx` and mobile `i18n.ts` (`policyPoints`), in both languages.
- **Privacy rules**: the customer never sees the driver's phone. After paying they get an encrypted WhatsApp link (`/chat/<Fernet token>`) that opens the business WhatsApp number with a 6-digit chat PIN; the relay forwards messages between registered numbers. Aadhaar: only the last 4 digits are stored. GPS points are accepted only between start and end codes and purged after 90 days.
- **Payment return**: payment-service redirects to `WEB_URL/dashboard?booking=<id>&payment=paid|cancelled|failed` (web) or `vandiottunar://payment?booking=…&payment=…` (app). `cancelled` = cancellation fee paid and booking cancelled.

### Owner's local setup (Windows)

- PowerShell, one `.venv` per service; always run tools as `python -m …` (`python -m uvicorn`, `python -m alembic`, `python -m pytest`).
- PostgreSQL 18 on `localhost:5432`, user `postgres`, password `admin`; create each database in pgAdmin once.
- VS Code: open `vandiottunar-frontend/vandiottunar.code-workspace`; tasks start every service on folder open (migrate first) and `npm run dev`.
- After pulling: `python -m alembic upgrade head` in each service that has new migrations.

### Rules for working on this project (Claude, read this)

1. **Web and mobile stay in step.** Any user-facing change in `web/` must also be made in `mobile/` (driver and customer sides) unless it is truly web-only (e.g. the admin panel). Say explicitly if something can't be mirrored.
2. **Both languages.** Add every new string to `en` *and* `ta` (web `src/i18n.tsx`, mobile `src/i18n.ts`). Plain, friendly wording; no jargon.
3. **Migrations.** Every model change gets an Alembic migration (`python -m alembic revision --autogenerate -m "…"`), checked with `python -m alembic check`. New NOT NULL columns need a `server_default` so existing rows migrate (this broke once).
4. **Tests.** Each service has pytest suites on SQLite (`python -m pytest -q`). Add tests for new rules. Web: `npx tsc -b && npm run build && npm run lint`. Mobile: `npx tsc --noEmit && npx expo export --platform android`.
5. **Cross-service contracts** live in this file. If you change an internal endpoint, a JWT claim, a status value or a redirect URL, update the CLAUDE.md in every repo.
6. **Secrets** only in `.env` (never committed). Keep `.env.example` complete and commented. Production refuses to start with dev settings (`validate_for_runtime`).
7. **Feature log.** When you add or change a feature, add a line to the *Feature log* in the CLAUDE.md of every repo it touches.
8. Commit messages: what changed and why, in plain words.
