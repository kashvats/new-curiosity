# Build Report — Part 1: Agent Runtime + Recursive Repair Foundation

**Date:** 2026-09-15

## Objective

Create the first stable implementation slice of the agentic coding/self-improvement architecture without attempting autonomous scheduling yet.

## Delivered

- Core agent registry with Context, Planner, Coder, Debugger, Tester, and Reviewer roles.
- Restored missing `app.coder` and `app.apply_changes` source contracts.
- Capability registry and role-based model selection.
- Isolated candidate workspaces.
- Safe change engine with path confinement, size/file-count limits, SHA-256 stale-write protection, and diff previews.
- Constrained command executor (`shell=False`, executable allowlist, cwd confinement, filtered environment, timeout/output caps).
- Verification service.
- Persistent repair-attempt storage and failure signatures.
- Bounded recursive repair loop that feeds verification failures back into the next LLM iteration.
- Cumulative candidate change materialization so a multi-attempt repair can be promoted as one complete result.
- Independent reviewer stage after machine verification.
- New `/agents`, `/agents/run`, and `/agents/repair` endpoints.
- Existing audit-fix apply path moved to the shared backup/safe-apply engine.
- New improvement/repair database tables.
- Test Generator router restored.
- Impact router made resilient to unavailable optional embedding dependencies during import.
- Canonicalized settings structure with legacy compatibility properties.

## Verification performed

```text
python -m compileall -q app tests
pytest -q tests/test_agent_foundation.py
```

Result:

```text
8 passed
```

The repair-loop test intentionally makes the first candidate fail Python compilation, then verifies that the second attempt succeeds while the live source remains unchanged.

## Known deferred work

The following legacy imports remain deliberately deferred to Part 2:

- `app.search`
- `app.qdrant_service`
- `app.knowledge_gap_detection`
- `app.rag_eval`
- `app.regression_detection`
- `app.change_timeline`

Additional Part 2 priorities:

- deterministic project-aware validation discovery,
- Security and Architecture agents,
- baseline/candidate quality score,
- persistent verified-candidate approval/promotion transaction,
- better context retrieval from symbols/import graph/memory,
- IDE activity streaming and diff-review integration.

## Stability boundary

Part 1 intentionally does **not** run recurring autonomous improvement cycles. The manual repair path needs to prove candidate isolation, validation, promotion, rollback, and memory first.
