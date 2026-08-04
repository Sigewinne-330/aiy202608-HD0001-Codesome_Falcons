# Project and Registration Analysis

## 1. What the project does

`ib-deadline-assistant` is a full-stack planning assistant for students. It combines task and deadline management, calendar views, long-term task decomposition, progress tracking, and AI chat. The current product is shaped for rapid hackathon delivery while retaining a conventional authenticated multi-user web architecture.

## 2. Current architecture

- **Frontend:** Vue 3 + Vite + Vuetify. Vue Router protects authenticated pages. A small Composition API auth store calls JSON endpoints and persists the JWT and user in `localStorage`.
- **Backend:** FastAPI with synchronous route handlers, Pydantic request/response schemas, SQLAlchemy ORM, and MySQL through PyMySQL.
- **Authentication:** bcrypt password hashes, signed JWT bearer tokens, and user lookup from the existing `user` table through `models.app_user.AppUser`.
- **Database lifecycle:** `Base.metadata.create_all()` plus a custom startup helper that adds missing columns. SQL bootstrap files are maintained manually; there is no migration framework.
- **Configuration:** a local ignored `backend/config.py` loads environment variables. Committed configuration documentation currently lives in the README and `.env.example`.

## 3. Current registration flow and relevant files

1. `frontend/src/views/RegisterView.vue` validates username, email, password, and password confirmation in the browser.
2. `frontend/src/stores/auth.js` posts username/email/password to `POST /api/auth/register`.
3. `backend/routers/auth.py` checks duplicate email and username, hashes the password, inserts an `AppUser`, and immediately returns a JWT.
4. The frontend stores the session and routes to `/calendar`.

Relevant files:

- `backend/routers/auth.py`
- `backend/services/auth.py`
- `backend/schemas/user.py`
- `backend/models/user.py`
- `backend/database.py`
- `backend/main.py`
- `backend/init_db.sql`
- `frontend/src/views/RegisterView.vue`
- `frontend/src/stores/auth.js`
- `frontend/src/router/index.js`

## 4. Existing problems and risks

- Registration proves neither email ownership nor human intent, so automated bulk account creation is unrestricted.
- There is no email provider, verification state, expiry, one-time proof, resend throttling, failed-attempt budget, or IP/email rate limiting.
- Backend registration validation is weaker than browser validation and can be bypassed by direct API calls.
- The repository retains legacy bridge code that references a historical `users` table, while current auth uses the authoritative `user` table; the distinction can mislead future agents.
- Database evolution uses startup auto-sync/manual SQL rather than versioned migrations.
- There is no existing automated test harness.
- CORS permits all origins with credentials and the README documents an insecure default JWT secret. These pre-existing issues should be resolved before production deployment.
- Local `main` was seven commits behind its remote tracking branch during analysis, so remote changes may need reconciliation before publishing.

## 5. Best implementation approach

Use a dedicated pre-registration verification record and a two-step proof flow:

1. Request a code for a normalized email.
2. Send a six-digit code through an SMTP-backed email abstraction.
3. Verify the code against an HMAC digest, expiry, current-code status, and failed-attempt budget.
4. Return a high-entropy, one-time registration proof whose digest is stored server-side.
5. Require that proof during registration and atomically consume it when the user is created.

Persist request history so cooldown and rolling per-email/per-IP limits survive process restarts. Supersede old codes when a new code is issued, use generic request responses to reduce email enumeration, and invalidate verification state if the user changes the email. On the frontend, present account details, code entry, resend countdown, loading, and recoverable failure states as one focused registration flow.

## 6. Recommended AI development workflow

Use OpenSpec as the durable source of truth:

`Explore → Proposal → Design → Tasks → Implementation → Verification → Archive`

Agents should inspect existing patterns first, create or update the feature artifacts before product code, keep tasks small and verifiable, implement only approved scope, run focused tests plus regression checks, synchronize the specification with any implementation decision, and archive completed changes with evidence.
