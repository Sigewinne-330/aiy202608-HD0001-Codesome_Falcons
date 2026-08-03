# Task Plan

## Goal

Establish a professional OpenSpec-driven AI development environment for this repository, then specify, implement, and verify email verification before registration without unrelated product changes.

## Phases

| Phase | Status | Evidence / Exit Criteria |
|---|---|---|
| 1. Repository and authentication analysis | complete | Architecture, registration flow, relevant files, risks, and recommended approach documented; no application code changed |
| 2. OpenSpec and Codex setup | complete | Latest OpenSpec installed/configured; Explore → Proposal → Design → Tasks → Implementation → Verification → Archive accessible |
| 3. Repository AI rules and reusable templates | complete | Rules, four requested templates, and competition checklist created |
| 4. Email-verification proposal/spec/design/tasks | complete | Goal, requirements, scenarios, acceptance criteria, edge cases, security design, and task breakdown complete |
| 5. Feature implementation | complete | Backend/frontend changes follow approved artifacts and existing architecture |
| 6. Tests and verification | complete | Required success/failure/rate-limit/expiry/reuse/email-failure cases and regressions pass |
| 7. Completion audit and final report | complete | Every objective requirement mapped to authoritative evidence; final report delivered |

## Machine-Readable Phase Status

### Phase 1: Repository and Authentication Analysis
- **Status:** complete

### Phase 2: OpenSpec and Codex Setup
- **Status:** complete

### Phase 3: AI Rules and Reusable Templates
- **Status:** complete

### Phase 4: Email Verification OpenSpec Artifacts
- **Status:** complete

### Phase 5: Feature Implementation
- **Status:** complete

### Phase 6: Tests and Verification
- **Status:** complete

### Phase 7: Completion Audit and Final Report
- **Status:** complete

## Constraints

- Do not implement product code before repository analysis and OpenSpec artifacts are complete.
- Preserve existing architecture and avoid unrelated refactors.
- Store only hashed verification codes; address expiry, one-time use, brute force, resend abuse, email enumeration, and send failures.
- Keep the feature demo-ready and dependency-light.

## Current Assumptions to Verify

- The target application is `cf/ib-deadline-assistant`.
- Backend is FastAPI/Python and frontend is Vue/Vite.
- The workspace top-level `cf` directory may contain product requirements but is not necessarily the repository root.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---|---|
| System `python3` lacks SQLAlchemy while checking the new backend modules | 1 | Compile step succeeded; locate/use the project virtual environment or install requirements into an isolated task environment before runtime tests |
| `dnspython` download timed out while installing the isolated backend environment | 1 | pip resumed the download automatically and installed all requirements successfully |
| Playwright skill wrapper could not find its documented `playwright-cli` binary | 1 | Do not repeat the wrapper call; use the available browser-use automation fallback for the same local UI verification |
| Vite development port 5173 was already occupied | 1 | Vite selected 5174 automatically; UI verification targets `http://127.0.0.1:5174` |
| `planning-with-files` completion script reported 0/0 because the phase table was not in its parseable heading format | 1 | Add explicit phase headings/status markers matching the skill template, then rerun the check |
| Goal completion API reported that this thread has no active goal | 1 | Do not repeat the status mutation; retain the verified 7/7 local completion evidence and report the API state in handoff |
