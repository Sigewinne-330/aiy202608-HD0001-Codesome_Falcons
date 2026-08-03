# Findings

## Initial Repository Discovery

- The workspace contains a likely application at `cf/ib-deadline-assistant`.
- Backend files indicate FastAPI-style routers, SQLAlchemy-style models/schemas, SQL migration scripts, and Python requirements.
- Frontend files indicate Vue, Vite, Vuetify, a client-side auth store, and dedicated login/register views.
- Authentication-related candidates include:
  - `backend/routers/auth.py`
  - `backend/services/auth.py`
  - `backend/models/user.py`
  - `backend/models/app_user.py`
  - `backend/schemas/user.py`
  - `frontend/src/stores/auth.js`
  - `frontend/src/views/RegisterView.vue`
- The workspace also contains `cf/需求文档.md`, `cf/README.md`, and a separate `chatbot_test`; their relationship to the app still needs verification.

## Confirmed Project Shape

- Git root is `cf`; `ib-deadline-assistant` is the target full-stack app inside that repository.
- Product purpose: an IB/long-term task planning assistant with task decomposition, progress, calendar/deadline management, and AI chat.
- Backend stack: Python 3.10+, FastAPI 0.115.6, SQLAlchemy 2.0.36, MySQL/PyMySQL, Pydantic 2, JWT via python-jose, bcrypt.
- Frontend stack: Vue 3.5, Vite 6, Vue Router 4.5, Vuetify 3.9.
- Documented auth API is `/api/auth/register`, `/api/auth/login`, and `/api/auth/me`.
- There is no test dependency or test script in the current Python/Node manifests, so a test harness likely needs to be added.
- The README documents environment-driven DB/JWT configuration and mentions `backend/config.py` plus `.env.example`; current file discovery did not show either, so documentation/current-tree drift must be checked.
- Vite proxies `/api` to `http://127.0.0.1:8000`.

## Current Registration and Authentication Architecture

- Registration is a single synchronous `POST /api/auth/register` call. It checks duplicate email and username, hashes the password with bcrypt, inserts `models.user.User`, issues a JWT, and returns the user/session immediately.
- Login looks up the same `users` table by email and validates bcrypt; protected routes use OAuth2 bearer extraction plus JWT `sub` lookup.
- `schemas.user.UserCreate` currently accepts username/email/password with little backend validation: email is typed as plain `str` despite importing `EmailStr`; password/username length constraints only exist in the browser.
- The registration UI is one form with username, email, password, and confirmation. On submit it calls `useAuth().register(...)`, stores JWT/user in `localStorage`, and routes to `/calendar`.
- No email service, code request/verification endpoint, verification state, resend timer, or server-side abuse control is present in inspected auth code.
- Authoritative registration uses `models.user.User` / SQL table `users`. A second `AppUser` model targets legacy/new table `user`; it is imported into shared metadata but is not used by auth, creating model/schema ambiguity.
- Database startup calls `Base.metadata.create_all` plus a custom add-missing-columns synchronizer. SQL bootstrap is `backend/init_db.sql`; no formal migration framework is present.
- Current CORS allows all origins with credentials, and the documented default JWT secret is unsafe for production. These are existing security risks outside the feature's narrow implementation scope but should be reported.

## Repository State and Risks

- Git repository root: `cf`.
- Branch `main` is 7 commits behind `origin/main` at inspection time. No tracked local modifications were reported; the three planning files are newly untracked files created for this task.
- `backend/config.py` is intentionally ignored, so configuration changes must be represented in a committed example/documentation file rather than relying on the local ignored file.
- There is no declared test framework in backend requirements and no frontend test script.
- Frontend validation can be bypassed; backend validation must become authoritative for any registration security boundary.

## Configuration, Documentation, and Test Baseline

- Local ignored `backend/config.py` exposes settings for app metadata, MySQL, two AI providers, and JWT only. There are no SMTP/email or verification-policy settings.
- Repository-wide search found no mail transport/provider implementation.
- Top-level requirements frame the product as a hackathon-oriented school/IB planning assistant; fast delivery and demo readiness are legitimate priorities, but the product document also calls out safety guardrails.
- No backend or frontend test files/configuration were found in the app tree.

## Recommended Email Verification Design (Phase 1 Conclusion)

- Add a dedicated `email_verifications` persistence model/table rather than adding transient fields to `users`; this preserves request history for rate limiting and cleanly separates pre-registration state.
- Normalize email server-side and validate all registration fields with Pydantic constraints.
- Add two pre-registration endpoints: request code and verify code. Verification returns a high-entropy registration proof; registration requires and atomically consumes that proof.
- Store the six-digit code as an HMAC digest (using the application secret), never plaintext. Store the high-entropy proof as a one-way SHA-256 digest.
- A new request supersedes prior unconsumed codes for the same email. Track expiry, failed attempts, verified time, consumed time, request IP, and timestamps.
- Enforce resend cooldown and rolling per-email/per-IP request limits in the database; lock a code after a small failed-attempt budget.
- Return a generic response from code-request calls to reduce email enumeration. Do not send a code for an already registered address.
- Use a small email-service abstraction backed by SMTP configuration and dependency injection so send failures/timeouts can be handled and tested without external calls.
- Frontend should use a three-state flow (account details → code verification → registration completion), with loading/error states, resend countdown, and reset when email changes.
- Add a lightweight pytest/FastAPI test harness with an isolated SQLite database and mocked email sender; keep frontend verification proportional via production build unless a UI unit-test framework is introduced.

## OpenSpec Version and Codex Integration Research

- The live npm registry reports `@fission-ai/openspec` **1.7.0** as latest on 2026-08-03. This is newer than the web search index's cached 1.6.0 package page, so npm registry/current CLI output is authoritative.
- OpenSpec 1.7.0 is already installed globally at `/opt/homebrew/bin/openspec`; `openspec --version` returns 1.7.0.
- Local Node.js is 25.7.0, satisfying OpenSpec's documented Node.js >= 20.19 requirement.
- OpenSpec 1.7.0 natively accepts `codex` in non-interactive `openspec init --tools ...`.
- Official OpenSpec materials describe the artifact-guided workflow and generated Codex skills. The expanded/custom profile is needed because verification is not part of the smallest core skill set.
- The installed global profile is already `custom`, delivery mode `both`, with workflows `propose`, `explore`, `apply`, `update`, `sync`, `archive`, and `verify` explicitly enabled.
- The packaged `spec-driven` schema resolves the requested artifact order: proposal → specs → design → tasks. Apply covers implementation; verify and archive complete the requested lifecycle.
- Initializing with `--tools codex --profile custom` generates the Codex integration while keeping shared OpenSpec artifacts agent-agnostic.

## OpenSpec Initialization Result

- `openspec init . --tools codex --profile custom --force --no-animation` completed successfully.
- CLI reported 7 Codex skills. Commands are intentionally skipped because the current integration invokes skills directly.
- `openspec/config.yaml` uses the packaged `spec-driven` schema.
- `openspec doctor --json` reports the project root healthy with no relationship issues; `openspec list --json` resolves the project and currently shows no active changes.
- The expected root `AGENTS.md` was not present after init despite older/cached official material mentioning one; current generated files need direct enumeration before choosing the repository instruction-file location.
- Direct enumeration confirmed 7 Codex OpenSpec skills covering explore, propose, apply, update, sync, verify, and archive.
- Generated skill metadata records `generatedBy: "1.7.0"`; command content delegates artifact structure and operation guidance back to the current OpenSpec CLI, reducing template drift.

## Open Questions

- Exact Git/repository root and current worktree status.
- Which user model and registration endpoint are authoritative.
- Database engine and migration strategy.
- Whether an email provider/configuration already exists.
- Existing test framework and baseline health.
- Whether the seven remote commits materially change auth; the current worktree remains authoritative unless explicitly synchronized.
