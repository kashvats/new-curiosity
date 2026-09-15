# Build Part 4 Report — Manual Self-Improvement Controller

**Date:** 2026-09-15

## Goal

Implement the next safe layer above the Part 3 IDE runtime: a measurable, manually-triggered project improvement cycle that reuses the existing isolated repair, verification, review, security, promotion, snapshot and rollback services.

Part 4 deliberately does **not** enable recurring autonomous scheduling or unattended source promotion.

## New modules

- `app/project_health.py`
- `app/improvement_brain.py`
- `app/improvement_store.py`
- `app/improvement_controller.py`
- `app/improvement_api.py`
- `tests/test_part4_improvement.py`

## Major improvements

### 1. Unified deterministic project-health snapshot

`project_health.py` now produces a normalized score with five dimensions:

- tests,
- security,
- architecture,
- quality,
- knowledge/documentation.

The snapshot is based on bounded source inspection plus the same safe project checks already used by the IDE/repair runtime. It never requires an LLM and never writes to the target project.

The health result includes:

- overall score,
- dimension scores,
- discovered machine-check results,
- bounded metadata,
- actionable findings with evidence and suggested validation.

### 2. Improvement Agent

The shared `AgentRegistry` now exposes a tenth role:

```text
improvement
```

The Improvement Agent converts measured health findings into small, evidence-backed candidates using deterministic logic. It does not invent broad refactors when there is no finding.

### 3. Candidate generation and prioritization

Each candidate carries:

- problem,
- evidence,
- proposed task,
- likely files,
- validation plan,
- risk,
- benefit,
- confidence,
- urgency,
- estimated cost,
- deterministic priority score.

Priority follows the roadmap shape:

```text
benefit × confidence × urgency / (risk × cost)
```

Part 4 only selects risks allowed by policy. Default eligible risks are `low,medium`.

### 4. Persisted improvement-cycle state machine

Manual cycles now persist state and events through:

```text
IDLE
  -> OBSERVING
  -> DIAGNOSING
  -> PROPOSING
  -> VALIDATING
  -> WAITING_APPROVAL
  -> APPLYING
  -> MONITORING
  -> LEARNING
  -> IDLE
```

Failure/stop states include:

- `VALIDATION_FAILED`
- `BLOCKED_BY_CAPABILITY`
- `BUDGET_EXCEEDED`
- `ROLLBACK_REQUIRED`

Every state transition and nested repair event is append-only and streamable.

### 5. Manual and observe-only policies

Part 4 supports only:

- `manual` — may prepare a verified candidate, but live source writes require explicit `confirm=true`.
- `observe_only` — captures health and recommendations but never enters the repair loop.

`guarded` and recurring autonomous policies are intentionally not enabled yet.

### 6. Shared repair loop integration

The improvement controller does not create a second coding path. A selected improvement becomes a normal `RepairIssue` and goes through:

- isolated candidate workspace,
- Debugger/Coder retry loop,
- machine verification,
- regression checks,
- independent Reviewer,
- deterministic Security gate,
- Quality score,
- exact verified-candidate persistence.

Repair attempts now retain the originating `cycle_id`.

### 7. Post-apply health monitoring and outcome memory

After explicit approval:

1. the exact verified candidate is applied with the existing snapshot protection,
2. persisted machine checks run again,
3. a new health snapshot is captured,
4. baseline and final scores are compared,
5. the measured outcome is stored in `improvement_outcomes`.

The system now remembers measured results rather than merely generated patches.

### 8. Health-regression rollback

If the post-apply health score drops more than the configured threshold, the controller restores the pre-apply snapshot and records the rollback as the cycle outcome.

Default threshold:

```text
IMPROVEMENT_MAX_SCORE_REGRESSION=3
```

### 9. Explicit rollback endpoint for applied repairs

Applied verified repairs can now be intentionally restored using their promotion snapshot:

```text
POST /agents/repairs/{issue_id}/rollback
```

This keeps the original `applied_at` audit timestamp while recording rollback state and reason.

## New database state

New tables:

- `project_health_snapshots`
- `improvement_events`
- `improvement_outcomes`

Expanded existing tables:

- `improvement_cycles`
- `improvement_candidates`

The migrations are backward-compatible with the Part 1–3 SQLite schema.

## New HTTP API

```text
GET  /improvements/capabilities
GET  /improvements/health
GET  /improvements/health/latest
GET  /improvements/health/{snapshot_id}
POST /improvements/cycles
GET  /improvements/cycles
GET  /improvements/cycles/{cycle_id}
GET  /improvements/cycles/{cycle_id}/events
GET  /improvements/cycles/{cycle_id}/events/stream
POST /improvements/cycles/{cycle_id}/apply
GET  /improvements/outcomes

POST /agents/repairs/{issue_id}/rollback
```

## Safety boundaries retained

- no self-starting scheduler,
- no automatic source apply,
- no shell command bypass,
- no live-project edits during candidate generation,
- exact candidate promotion only,
- stale-hash and protected-path checks remain active,
- machine verification remains mandatory,
- independent review/security gates remain mandatory,
- live apply remains snapshot-protected,
- material health regression triggers rollback.

## Configuration added

```text
IMPROVEMENT_DEFAULT_POLICY=manual
IMPROVEMENT_ALLOWED_RISKS=low,medium
IMPROVEMENT_MAX_CANDIDATES=8
IMPROVEMENT_MAX_FILES=8
IMPROVEMENT_ACCEPTABLE_HEALTH_SCORE=92
IMPROVEMENT_MIN_PRIORITY=0.05
IMPROVEMENT_MAX_SCORE_REGRESSION=3
IMPROVEMENT_SOURCE_SCAN_FILES=400
IMPROVEMENT_SOURCE_SCAN_BYTES=2000000
```

## Verification

Commands executed:

```bash
python -m compileall -q app tests
pytest -q
```

Result:

```text
41 passed
```

Backend import smoke test:

```text
IMPORT_FAILURES 0
```

Part 4 tests cover:

- schema creation/migration,
- Improvement Agent registration,
- deterministic candidate prioritization,
- real passing project-health machine checks,
- observe-only cycle behavior,
- manual cycle verified-candidate boundary,
- outcome persistence,
- health-regression rollback,
- explicit applied-repair rollback,
- API route registration.

## Deliberately deferred to Part 5

The next safe slice should focus on learning quality and controlled experimentation before any scheduler is enabled:

- strategy-performance statistics across cycles,
- retrieve successful/failed outcomes when ranking new candidates,
- experiment mode with multiple isolated candidate approaches,
- API-contract and architecture-drift baselines,
- dependency-health intelligence,
- resource/compute budgets,
- user-selectable candidate override,
- guarded policy only after enough manual outcome history exists,
- recurring scheduler last.
