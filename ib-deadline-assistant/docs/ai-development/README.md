# AI Development Workflow

This repository uses OpenSpec 1.7.0 with its native Codex integration.

## Start a feature

1. Read `AGENTS.md` and inspect the relevant code path.
2. Explore the idea without changing artifacts or product code.
3. Create an OpenSpec change proposal and all required artifacts.
4. Review Goal, requirements, scenarios, acceptance criteria, edge cases, design, and tasks.
5. Apply the change, verify it, synchronize the durable specs, and archive it.

### Codex

- `$openspec-explore`
- `$openspec-propose <feature description>`
- `$openspec-apply-change <change-name>`
- `$openspec-verify-change <change-name>`
- `$openspec-sync-specs <change-name>`
- `$openspec-archive-change <change-name>`

Restart Codex after initialization or `openspec update` so generated skills are reloaded.

## Maintenance

Check for and install the latest CLI, then refresh project integrations:

```bash
npm install -g @fission-ai/openspec@latest
openspec update
openspec doctor
```

Use `openspec list`, `openspec status --change <name>`, and `openspec validate <name>` to inspect workflow state.
