# Build Part 3 Report — IDE Runtime & Verified Promotion

## Goal

Build the first real IDE-facing coding-agent layer on top of the safe Part 1/2 backend without creating a second coding path. Ask, Plan, Edit, Fix, Review and Agent modes all use the same project context, repair, verification, reviewer/security, verified-candidate, snapshot and rollback services.

## Implemented

### IDE session runtime

New modules:

- `app/ide_store.py` — persistent IDE sessions and append-only activity events.
- `app/ide_service.py` — mode orchestration.
- `app/ide_api.py` — FastAPI IDE endpoints and SSE event stream.
- `app/context_builder.py` — bounded project-aware context.
- `app/test_discovery.py` — deterministic quick/regression check discovery.
- `app/project_navigation.py` — repository tree, text search and symbol search.

New SQLite tables:

- `ide_sessions`
- `ide_events`

### IDE modes

- `ask`: project-aware answer, no writes.
- `plan`: project-aware implementation plan, no writes.
- `review`: independent reviewer + deterministic security scan, no writes.
- `edit`: verified patch flow with a shorter default retry budget.
- `fix`: full bounded diagnose → patch → verify → retry loop.
- `agent`: inspect context → plan → repair → verify → review → security → quality → verified candidate.

### Richer context

The context builder now collects bounded evidence from:

- current/selected files,
- local Python import neighbors,
- related conventional tests,
- editor selection,
- editor diagnostics,
- supplied terminal output,
- read-only Git status/diff,
- discovered project verification commands.

The existing Context Agent now uses this richer context builder too.

### Automatic regression discovery

The repair loop no longer relies only on a Coder-supplied check. After targeted checks pass it can automatically run broader discovered checks, including:

- Python `compileall`,
- targeted pytest files when conventionally discoverable,
- full pytest regression suite,
- Ruff when configured,
- npm typecheck/check,
- npm tests,
- npm lint.

All commands still pass through `safe_commands.py` and `shell=False` policy.

### Streamed agent activity

`repair_issue()` now emits non-fatal structured events for:

- repair start,
- candidate workspace ready,
- attempt start,
- debugger diagnosis,
- candidate drafted,
- validation start/result,
- reviewer result,
- security result,
- quality score,
- failed attempt,
- verified candidate,
- bounded stop reason.

IDE sessions persist these events and expose a Server-Sent Events stream.

### Post-apply regression + automatic rollback

Verified promotion is stronger in Part 3:

1. load the exact candidate that previously passed all gates,
2. stale-content checks still run,
3. snapshot live project,
4. apply exact candidate,
5. re-run the persisted machine checks,
6. automatically restore the snapshot if a check fails,
7. persist `applied` or `rolled_back` state and timeline evidence.

Legacy verified candidates that predate persisted check commands recover safe deterministic checks through project test discovery instead of silently skipping verification.

### Repository navigation APIs

- project tree,
- bounded case-insensitive code/text search,
- functions/classes symbol search,
- no LLM or vector database required for these basic navigation operations.

### VS Code extension 1.1.0 source

The extension now provides:

- Ask
- Plan
- Edit
- Fix
- Review
- Agent
- Show Agent Activity
- Show Last Verified Diff
- Apply Last Verified Repair
- Browse Repository
- Search Code
- Search Symbols
- existing Audit / History / Security commands retained

Write modes stream backend activity, use native VS Code diff previews, and require explicit application. Apply warns that a snapshot and post-apply checks will run and reports automatic rollback if those checks fail.

## HTTP API added

```text
GET  /ide/modes
POST /ide/sessions
GET  /ide/sessions/{session_id}
GET  /ide/sessions/{session_id}/events
GET  /ide/sessions/{session_id}/events/stream
POST /ide/sessions/{session_id}/apply
GET  /ide/context
GET  /ide/test-discovery
GET  /ide/tree
GET  /ide/code-search
GET  /ide/symbols
```

## Verification

```text
python -m compileall -q app tests
PASS

pytest -q
31 passed

all app.* modules import individually
IMPORT_FAILURES 0

node --check vscode-extension/extension.js
PASS

package.json JSON validation
PASS
```

New tests cover:

- IDE DB tables,
- Python check discovery,
- project-aware context + related tests/imports,
- ordered persistent IDE events,
- Ask mode context usage,
- repair-loop event emission across a failed first attempt and successful retry,
- post-apply verification failure + automatic snapshot rollback,
- IDE route registration,
- repository tree/search/symbol navigation.

## Deliberately deferred

Part 3 does **not** enable autonomous recurring self-improvement yet. The next safe slice is to build the improvement controller on top of this now-observable, rollback-capable runtime:

- unified project health snapshot,
- Improvement Agent,
- candidate generation/prioritization,
- improvement-cycle persistence/state machine,
- outcome memory,
- manual improvement-cycle UI first,
- guarded scheduling only after manual cycles are proven.
