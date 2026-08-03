# Project AI Development Instructions

These instructions apply to Codex and any other AI coding agent working in this repository.

## OpenSpec workflow

For every non-trivial feature or behavior change, use this lifecycle:

`Explore → Proposal → Design → Tasks → Implementation → Verification → Archive`

- Explore the repository and related behavior before proposing changes.
- Do not implement a large feature until an OpenSpec change contains a clear proposal, specification, design, and task breakdown.
- Treat `openspec/changes/<change-name>/` as the source of truth while a change is active.
- Keep specs and tasks synchronized when implementation reveals a new constraint or decision.
- Verify code and tests against every requirement and scenario before archiving.
- Archive only when required tasks are complete and verification has no critical issue.

Codex workflows live under `.codex/skills/`.

## Requirements management

Every feature must define:

- Goal
- Requirement
- Scenario
- Acceptance Criteria
- Edge Cases

If any item is materially unclear, resolve it in the OpenSpec artifacts before coding. Never implement a large feature from a chat-only description.

## Development principles

- Prefer the simplest solution that satisfies the accepted requirements.
- Build a demo-ready MVP first.
- Avoid unnecessary dependencies and speculative abstractions.
- Preserve the existing FastAPI/SQLAlchemy and Vue/Vite architecture.
- Avoid breaking existing behavior and do not refactor unrelated code.
- Keep security boundaries and server-side validation authoritative on the backend.

## Before coding

- Inspect related files and trace the current behavior end to end.
- Understand existing project patterns and constraints.
- Read the active proposal, specs, design, and tasks from disk.
- Explain the implementation plan and identify how each task will be verified.

## During coding

- Make focused, minimal changes.
- Keep code readable and follow existing naming, layout, and API conventions.
- Reuse existing utilities when they are fit for purpose.
- Update the active Spec or design when implementation decisions change.
- Mark OpenSpec tasks complete only after their verification method passes.

## After coding

- Run focused tests, relevant regression tests, backend checks, and the frontend production build.
- Check runtime and build output for errors or warnings introduced by the change.
- Synchronize documentation and Specs with the implemented behavior.
- Run the OpenSpec verification workflow before archive.

## Rapid competition development

- Prioritize the smallest coherent demo path that proves user value.
- Keep the critical path reliable and make external-service failures recoverable.
- Defer polish and optional abstractions explicitly as non-goals.
- Use `docs/ai-development/competition-checklist.md` for every feature.
