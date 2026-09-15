# Build Part 2 Report — Stability, Specialist Agents, Legacy Contract Repair

**Date:** 2026-09-15

## Goal

Build on the tested Part 1 agentic repair foundation without starting an autonomous scheduler too early. The main objectives were to eliminate broken active imports, repair document/RAG schema drift, add specialist gates, make old orchestration use the safe loop, and persist exact verified candidates for later approval.

## New modules

- `app/project_paths.py`
- `app/qdrant_service.py`
- `app/search.py`
- `app/change_timeline.py`
- `app/knowledge_gap_detection.py`
- `app/regression_detection.py`
- `app/rag_eval.py`
- `app/security_review.py`
- `app/quality_scorer.py`
- `app/verified_candidate_store.py`
- `tests/conftest.py`
- `tests/test_part2_stability.py`
- `pytest.ini`

## Major improvements

### 1. All previously missing active module contracts restored

The active code paths that referenced `search`, `qdrant_service`, `knowledge_gap_detection`, `rag_eval`, `regression_detection`, and `change_timeline` now have real source modules.

### 2. Database drift repaired

The existing codebase had multiple generations of ingestion code using different field names. The schema is now a backward-compatible superset and initialization migrates old databases with missing columns.

`insert_document()` normalizes legacy fields and filters to live table columns. Chunk helpers support both `text` and `content` representations.

### 3. Optional dependency resilience

- sentence-transformers is imported only when embeddings are actually requested,
- qdrant-client is imported only for vector operations,
- watchdog absence disables watching without breaking backend imports,
- planner no longer needs LangGraph just to run a two-attempt workflow.

Result: every `app/*.py` module imports successfully in the current environment.

### 4. Security Agent

A deterministic gate now catches high-risk generated patterns before promotion, including `shell=True`, dynamic eval/exec, unsafe pickle/YAML patterns, likely hard-coded credentials, SQL interpolation, and disabled TLS verification.

Critical/high findings reject the candidate and become repair-loop evidence.

### 5. Architecture and Research agents

The runtime now exposes nine agents total. Architecture provides a deterministic project profile and Research wraps the existing explicit web-search capability.

### 6. Reviewer/Security/Quality rejection now loops

Machine-pass no longer means success. The candidate must also pass:

- Reviewer Agent,
- Security Agent,
- Quality scorer.

If any gate rejects it, the full result is stored and sent into the next Debugger/Coder attempt.

### 7. Safer command policy

The command runner now checks both executable and subcommand. An executable allowlist alone was not safe because `python -c` and mutating Git commands can perform arbitrary writes.

Examples now blocked:

- `python -c ...`
- `git reset --hard`
- arbitrary npm scripts
- `ruff format`
- parent-directory/absolute-path arguments

### 8. Protected source paths

Agent patches cannot change `.env`, `.git/`, or the assistant SQLite database by default. `.env.example` remains editable.

### 9. Exact verified-candidate persistence

A successful cumulative repair is stored in `verified_repairs`. This solves the gap where a temporary candidate workspace was destroyed after verification and the only copy of the verified proposal existed in an HTTP response.

New endpoints:

- `GET /agents/repairs/{issue_id}`
- `POST /agents/repairs/{issue_id}/apply`

Application requires explicit `confirm=true`, reuses stale hashes, takes a snapshot, applies, and writes a timeline event.

### 10. Old orchestrator hardened

The old Planner → Coder → direct Apply path is removed. Orchestration now calls the shared repair loop for every phase. Manual approval is the default; optional auto-apply occurs only after all shared gates pass.

## Verification

Commands executed:

```bash
python -m compileall -q app tests
pytest -q
```

Result:

```text
21 passed
```

An AST scan found no references to missing `app.*` modules.

A full backend import smoke test imported every `app/*.py` module:

```text
IMPORT_FAILURES 0
```

FastAPI route smoke checks confirmed:

- `/agents`
- `/agents/run`
- `/agents/repair`
- `/agents/repairs/{issue_id}`
- `/agents/repairs/{issue_id}/apply`
- `/search`
- `/tests/generate`
- `/impact/analyze`

Registered agents:

```text
architecture
coder
context
debugger
planner
research
reviewer
security
tester
```

## Important test added for the requested recursive behavior

A candidate intentionally introduces `subprocess.run(..., shell=True)`.

1. Python compilation passes.
2. Security Agent rejects the candidate.
3. The rejection is converted to `gate_failed` evidence.
4. The next Debugger/Coder attempt receives that evidence.
5. Attempt 2 changes it to `shell=False`.
6. Compile + Reviewer + Security + Quality all pass.
7. The live project is still unchanged until explicit apply.

This proves the repair loop is not limited to compiler/test failures; independent validation gates also feed the loop.

## Deferred intentionally

Part 2 does not yet add autonomous scheduling or continuous self-editing. It also does not yet implement the full IDE UI.

Recommended Part 3:

- project-aware test/check discovery,
- richer context builder,
- agent activity event stream,
- VS Code Ask/Plan/Edit/Fix/Review/Agent interface,
- diff approval UI,
- post-apply regression + rollback API,
- then improvement candidate/prioritization logic.
