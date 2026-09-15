# AI Coding Assistant — Agentic Self-Improving Engineering System

## 1. What this project is

This project is a local-first AI software-engineering platform. It is being built to combine the useful behavior of an IDE coding agent with a bounded self-improvement system.

The backend should be able to:

- understand a repository and its architecture,
- answer questions about code,
- plan implementation work,
- generate multi-file code changes,
- diagnose compiler/test/runtime failures,
- verify candidate fixes using real commands,
- send failed verification evidence back to the LLM and retry,
- independently review and security-check generated changes,
- keep exact verified candidates behind an approval boundary,
- snapshot and safely apply approved changes,
- remember failures and outcomes,
- and later identify and execute bounded improvements autonomously.

The system is **not** an unrestricted self-modifying process. The live project is not edited during repair attempts. Autonomous behavior must stay inside actual machine, model, tool, permission, resource, and policy limits.

## 2. Core engineering loop

```text
Issue / user request
        ↓
Capabilities + project context
        ↓
Debugger / Planner
        ↓
Coder
        ↓
Isolated candidate workspace
        ↓
Machine verification
   ┌────┴─────────┐
 FAIL             PASS
   ↓                ↓
Persist evidence   Reviewer Agent
   ↓                ↓
Debugger            Security Agent
   ↓                ↓
Coder again         Quality score
   ↓                ↓
Retry          reject ───→ retry loop
                    ↓ pass
             Persist exact verified candidate
                    ↓
               Human approval
                    ↓
             Snapshot + stale check
                    ↓
                  Apply
                    ↓
             Timeline / outcome
```

A failed attempt is not discarded. The next attempt receives the previous diagnosis, patch, validation plan, exact failure output, gate results, and failure signature.

## 3. Current agent runtime

The shared `AgentRegistry` currently exposes nine roles:

| Agent | Responsibility |
|---|---|
| Context | bounded project/file context |
| Planner | safe incremental implementation plan |
| Coder | structured create/modify proposals |
| Debugger | root-cause analysis using current evidence + attempt history |
| Tester | constrained machine verification |
| Reviewer | independent LLM review of a candidate |
| Security | deterministic fast security gate for generated code |
| Architecture | deterministic project manifest + structure profile |
| Research | explicit SearXNG research when requested |

Agents do **not** receive unrestricted filesystem or terminal access. Filesystem changes, process execution, model access, and promotion are delegated to constrained shared services.

## 4. Part 1 + Part 2 architecture

```text
FastAPI / VS Code / future Monaco IDE
                 │
                 ▼
            Agent Runtime
                 │
    ┌────────────┼───────────────────┐
    │            │                   │
Context       Reasoning          Specialist agents
Builder   Planner/Coder/Debug     Review/Security/
                                  Architecture/Research
    │            │                   │
    └────────────┴──────────┬────────┘
                            ▼
                    Candidate Workspace
                            │
                            ▼
                       Patch Engine
                            │
                            ▼
                  Verification Service
                            │
                 fail ──────┴──── pass
                  │                  │
                  └── Repair Loop ───┤
                                     ▼
                             Verified Candidate Store
                                     │
                                     ▼
                              Approval / Apply
                                     │
                                     ▼
                              Snapshot / Rollback
                                     │
                                     ▼
                             Timeline + Memory
```

The IDE and future self-improvement controller must use these same services. There should not be a second unsafe coding path.

## 5. Safety boundaries now implemented

### Candidate isolation

Repairs run against a temporary copy. The live source tree remains unchanged while the LLM retries.

### Patch controls

- create/modify only at this stage,
- relative paths only,
- path traversal blocked,
- configurable file/byte limits,
- protected paths such as `.env`, `.git/`, and the assistant database blocked,
- optional expected SHA-256 stale-content guard,
- unified diff preview.

### Command controls

Commands run with `shell=False`, bounded cwd, timeout, output limits, and filtered environment. Both executable and subcommand are checked.

Current safe policies include:

- `python -m compileall ...`
- `python -m pytest ...`
- `pytest ...`
- read-only Git: `status`, `diff`, `show`, `log`, `rev-parse`
- npm test/lint/typecheck/check/build scripts
- `ruff check`
- `mypy`

Commands such as `python -c ...` and `git reset --hard` are rejected even if the executable itself is allowlisted.

### Independent gates

A candidate that passes compilation/tests can still be rejected by:

1. Reviewer Agent,
2. Security Agent,
3. Quality scorer.

Gate rejection becomes new repair evidence and returns to Debugger → Coder → Verify instead of being treated as success.

### Exact verified promotion

Successful cumulative changes are persisted in `verified_repairs`. Approval later promotes the same verified content, with stale-file hashes checked again before live writes.

## 6. Restored and stabilized legacy features in Part 2

The previously missing active contracts are restored:

- `app/search.py`
- `app/qdrant_service.py`
- `app/knowledge_gap_detection.py`
- `app/rag_eval.py`
- `app/regression_detection.py`
- `app/change_timeline.py`

Additional stability improvements:

- document/RAG SQLite schema now supports both older and newer ingestion field names,
- legacy document inserts are normalized instead of failing on schema drift,
- chunk schema supports basic and section-aware chunkers,
- Qdrant is lazy-loaded,
- sentence-transformers is lazy-loaded,
- vector search falls back to SQLite keyword retrieval when embeddings/Qdrant are unavailable,
- watcher is optional when `watchdog` is absent,
- planner no longer requires LangGraph for a simple bounded retry loop,
- old orchestrator now routes phases through the shared repair engine instead of blindly applying LLM output,
- all backend modules can import in the current test environment even when optional vector/watcher packages are absent.

## 7. HTTP APIs

### Agent discovery

`GET /agents`

Returns registered agents and runtime capability facts.

### Run one agent

`POST /agents/run`

```json
{
  "agent": "architecture",
  "task": "Inspect this project",
  "project_name": "my-project",
  "files": [],
  "evidence": {}
}
```

### Bounded recursive repair

`POST /agents/repair`

```json
{
  "task": "Fix the failing order service test without changing its public API",
  "project_name": "my-project",
  "files": ["app/orders.py", "tests/test_orders.py"],
  "evidence": {
    "error": "AssertionError: expected 200, got 500"
  },
  "validation_plan": [
    {
      "args": ["pytest", "tests/test_orders.py", "-q"],
      "cwd": null,
      "purpose": "Reproduce and verify the original failure"
    }
  ],
  "max_attempts": 3
}
```

Successful output remains unapplied and includes an `issue_id`.

### Read the exact verified repair

`GET /agents/repairs/{issue_id}`

### Approve and apply

`POST /agents/repairs/{issue_id}/apply`

```json
{
  "confirm": true
}
```

The apply path creates a snapshot and performs stale-content checks before writing.

### Document retrieval

`POST /search`

Uses Qdrant when available and falls back to SQLite keyword search when the vector stack is unavailable.

## 8. Main implementation modules

| Module | Purpose |
|---|---|
| `app/agent_runtime.py` | registry + role adapters |
| `app/capabilities.py` | machine/tool capability facts |
| `app/project_paths.py` | central workspace/project confinement |
| `app/planner.py` | bounded plan generation + deterministic fallback |
| `app/coder.py` | structured coding proposals |
| `app/reviewer.py` | independent LLM review |
| `app/security_review.py` | fast deterministic security gate |
| `app/quality_scorer.py` | transparent candidate quality score |
| `app/candidate_workspace.py` | isolated candidate tree |
| `app/patch_engine.py` | path/payload/hash validation + diff/apply |
| `app/safe_commands.py` | executable + subcommand policy |
| `app/verification_service.py` | machine checks |
| `app/repair_attempt_store.py` | attempt/failure persistence |
| `app/repair_loop.py` | bounded diagnose → code → verify → retry loop |
| `app/verified_candidate_store.py` | exact verified candidate + approval promotion |
| `app/apply_changes.py` | snapshot/apply/rollback |
| `app/change_timeline.py` | change/test event history |
| `app/search.py` | document vector indexing + retrieval fallback |
| `app/regression_detection.py` | baseline/current report comparison |
| `app/knowledge_gap_detection.py` | deterministic missing/unhealthy knowledge report |
| `app/rag_eval.py` | retrieval eval runner |
| `app/agents_api.py` | agent, repair, retrieval, approval API |
| `app/orchestrator.py` | phased orchestration over the safe repair engine |

## 9. Configuration

Important values:

```env
DEBUGGER_MODEL=qwen2.5-coder:7b
REVIEWER_MODEL=qwen2.5-coder:7b
MAX_REPAIR_ATTEMPTS=4
MAX_PATCH_FILES=12
MAX_PATCH_BYTES=500000
COMMAND_TIMEOUT_SECONDS=120
MAX_COMMAND_OUTPUT_CHARS=40000
AGENT_ALLOWED_EXECUTABLES=python,python3,pytest,npm,git,ruff,mypy
AGENT_PROTECTED_PATHS=.env,.git/,data/ai_coder.db
```

Older lowercase settings references remain temporarily available through compatibility properties while legacy code is migrated.

## 10. Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API docs: `/docs`

## 11. Run tests

```bash
pytest -q
```

Part 2 verified baseline on 2026-09-15:

```text
21 passed
0 backend module import failures
```

The tests include candidate isolation, path traversal, stale writes, protected paths, safe command policies, recursive validation retry, **security-gate retry**, schema migration, keyword fallback, regression classification, timeline persistence, optional dependency imports, and exact verified-candidate promotion.

## 12. Next build slice

Part 3 should focus on the actual coding-IDE experience and richer project context:

1. build project-aware validation discovery (pytest/npm/ruff/mypy/etc.),
2. build a richer Context Builder using imports/symbols/tests/Git diff/memory,
3. add SSE/WebSocket agent activity events,
4. extend the existing VS Code extension with **Ask / Plan / Edit / Fix / Review / Agent** modes,
5. add file/selection/error/terminal context capture,
6. show diffs and verified-candidate approval in the IDE,
7. add post-apply regression monitoring and rollback endpoint,
8. only then add Improvement Agent candidate generation and scheduling.

See `SELF_IMPROVING_ORGANISM_README.md` for the full roadmap and `BUILD_PART_2_REPORT.md` for this slice's implementation details.

## 12. Part 3 — IDE Runtime

Part 3 turns the shared agent backend into a usable IDE-facing system without introducing a separate unsafe edit path.

### IDE modes

| Mode | Behavior |
|---|---|
| Ask | project-aware Q&A; read-only |
| Plan | incremental implementation plan; read-only |
| Review | reviewer + security inspection; read-only |
| Edit | small candidate patch with bounded retries |
| Fix | recursive diagnose → patch → check → failure evidence → retry |
| Agent | context → plan → edit/fix loop → reviewer → security → quality → verified candidate |

### Project context

`app/context_builder.py` gathers bounded source context, local Python import neighbors, conventional related tests, editor selection/diagnostics, optional terminal output, read-only Git status/diff, and deterministic test discovery. `ContextAgent` now uses the same builder.

### IDE sessions and activity

`app/ide_store.py` persists `ide_sessions` and append-only `ide_events`. `app/ide_api.py` exposes replay plus Server-Sent Events so IDE clients can show what the agent is doing without polling every internal step.

### Automatic regression checks

`app/test_discovery.py` identifies safe project checks. `VerificationService.verify_with_regression()` runs targeted checks first and broader discovered regression checks only after the targeted checks pass.

### Promotion is now rollback-verified

Applying a verified repair now creates a snapshot, applies the exact verified candidate, reruns machine checks against the live project, and restores the snapshot automatically if those checks fail. The repair record is persisted as `applied` or `rolled_back` with post-apply evidence.

### Repository navigation

`app/project_navigation.py` supplies basic IDE navigation independently of LLM/vector availability:

- repository tree,
- bounded code/text search,
- function/class symbol search.

### IDE API

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

### VS Code extension

`vscode-extension/` is now version `1.1.0` source and includes Ask, Plan, Edit, Fix, Review, Agent, streamed activity, native diff preview, explicit apply, repository browse, code search and symbol search while preserving the existing audit commands.

### Part 3 verification baseline

```text
pytest -q
31 passed

python -m compileall -q app tests
PASS

all app.* imports
IMPORT_FAILURES 0

node --check ../vscode-extension/extension.js
PASS
```

See `BUILD_PART_3_REPORT.md` for the exact changes and tests.

## 13. Next implementation slice

Build the first manually triggered self-improvement cycle using the same primitives rather than adding a second autonomy stack:

1. unified health snapshot,
2. Improvement Agent,
3. small candidate generator,
4. benefit/risk/confidence/cost prioritizer,
5. `improvement_cycles` state machine,
6. outcome memory,
7. manual trigger + inspection API/UI,
8. only then consider guarded scheduling.

## 14. Part 4 — Manual Self-Improvement Controller

Part 4 adds the first measurable improvement cycle on top of the Part 1–3 safety/runtime foundation. It still does **not** run an autonomous scheduler.

### Health snapshot

`app/project_health.py` creates a bounded, deterministic project-health snapshot covering tests, security, architecture, quality, and project knowledge/documentation. Machine checks are executed through the existing safe command policy.

### Improvement Agent and prioritizer

The runtime now has ten roles, adding `improvement`. Health findings become small candidates with evidence, risk, benefit, confidence, urgency, cost, likely files, validation plan, and a deterministic priority score.

### Manual cycle

```text
OBSERVING -> DIAGNOSING -> PROPOSING -> VALIDATING
          -> WAITING_APPROVAL -> APPLYING -> MONITORING
          -> LEARNING -> IDLE
```

The selected candidate is passed into the same isolated `repair_issue()` flow used by IDE Fix/Agent mode. Live writes remain blocked until explicit approval.

### Policies

- `manual`: prepare and verify, then wait for `confirm=true`.
- `observe_only`: health + recommendations only; no repair generation.

No recurring scheduler is enabled.

### Outcome memory and rollback

After apply, Part 4 captures a fresh health snapshot and stores the measured outcome. If health regresses beyond the configured tolerance, the pre-apply snapshot is restored. Applied repairs can also be explicitly rolled back through `/agents/repairs/{issue_id}/rollback`.

### Improvement API

```text
GET  /improvements/capabilities
GET  /improvements/health
POST /improvements/cycles
GET  /improvements/cycles/{cycle_id}
GET  /improvements/cycles/{cycle_id}/events/stream
POST /improvements/cycles/{cycle_id}/apply
GET  /improvements/outcomes
```

### Part 4 verification baseline

```text
pytest -q
41 passed

python -m compileall -q app tests
PASS

all app.* imports
IMPORT_FAILURES 0
```

See `BUILD_PART_4_REPORT.md` for implementation details.

## 15. Part 5 target — completed

The Part 4 recommendation was to add strategy/outcome learning, isolated experiments, API/architecture baselines, dependency intelligence, resource budgets, and manual candidate override before considering guarded autonomy. Those items are implemented below.

## 16. Part 5 — Outcome Learning, Controlled Experiments & Drift Guards

Part 5 makes the manual improvement controller materially smarter while preserving the Part 4 safety boundary. There is still **no recurring scheduler** and no live source apply without explicit approval.

### Outcome-aware ranking

Candidates now retain a deterministic `strategy_key` and base priority. Historical measured outcomes are grouped by strategy and summarized using sample count, successes, rollbacks, success rate and average health-score delta. Only after enough samples exist does a conservative learning multiplier influence ranking.

The history is inspectable through:

```text
GET /improvements/learning/strategies
```

### Manual candidate override

A cycle can set:

```json
{
  "pause_for_candidate_selection": true
}
```

and stop at `WAITING_SELECTION` before any repair LLM work is performed. The user can then choose an eligible candidate:

```text
POST /improvements/cycles/{cycle_id}/select
```

### Isolated experiment mode

Manual cycles can validate several eligible candidates independently:

```json
{
  "experiment_mode": true,
  "experiment_candidates": 2
}
```

Each candidate uses its own candidate workspace and the normal Debugger/Coder -> machine verification -> Reviewer -> Security -> Quality pipeline. Verified results are compared by quality and learned priority. The winner still stops at `WAITING_APPROVAL`.

Experiment history:

```text
GET /improvements/cycles/{cycle_id}/experiments
```

### Resource budgets

Part 5 adds cycle ceilings for candidate repairs, attempts, changed files and candidate patch bytes. Clients may request lower limits but cannot raise them above server configuration. Budget exhaustion stops the cycle in `BUDGET_EXCEEDED`.

### API/architecture drift baseline

An approved deterministic baseline can now be captured and compared against the current repository:

```text
POST /improvements/baselines
GET  /improvements/baselines
GET  /improvements/drift
```

The baseline tracks discovered HTTP route signatures and bounded source layout. Removed API routes are strong regression evidence, but drift findings are review-only by default so intentional contract changes are not automatically reverted.

### Offline dependency health

```text
GET /improvements/dependencies
```

The scanner detects reproducibility problems in `requirements*.txt` and `package.json`/lockfiles without contacting package registries. Findings that require choosing versions or regenerating lockfiles are not auto-targeted by default.

### Expanded project health

Health dimensions are now:

```text
tests
security
architecture
quality
knowledge
dependencies
drift
```

Tests and security remain dominant in the weighted score.

### Part 5 verification baseline

```text
pytest -q
49 passed

python -m compileall -q app tests
PASS

all app.* imports
IMPORT_FAILURES 0

node --check ../vscode-extension/extension.js
PASS
```

See `BUILD_PART_5_REPORT.md` for the exact implementation and safety details.

## 17. Part 6 — Governance, Impact Memory & Operator Controls

Part 6 implements the governance/observability layer proposed after Part 5. Recurring scheduling is still disabled and the human source-apply requirement cannot be disabled by project policy.

### Versioned project policies

Each project can now maintain an active, versioned improvement policy controlling risk, minimum priority, allowed/blocked finding categories, protected API routes, architecture invariants, dependency-manifest edits, and repeat suppression. Every improvement cycle snapshots the resolved policy so later policy edits do not silently change an in-flight cycle.

```text
GET /improvements/policies/{project_name}
PUT /improvements/policies/{project_name}
GET /improvements/policies/{project_name}/history
```

`approval.human_source_apply_required` is forced to `true` during normalization and cannot be disabled.

### Exact-patch governance gate

A verified repair is materialized into a throw-away candidate workspace and checked against deterministic governance before it can become the cycle winner. The same check is run again immediately before live apply. Rules cover:

- routes explicitly listed as protected,
- routes from the active approved API baseline that the candidate newly removes,
- required architecture paths,
- protected/forbidden paths,
- approved top-level source layout when enabled,
- maximum changed module size,
- optional dependency manifest/lockfile change prohibition.

Governance-blocked verified repairs are revoked so they cannot later be applied through another repair surface. Non-winning verified experiment repairs are also revoked.

```text
GET /improvements/governance/checks
```

### Repeated-candidate suppression

Candidates now carry a deterministic fingerprint based on strategy, health finding, risk, and likely files. Repeated attempted candidates are counted across prior project cycles. Once the configured repeat limit is reached, the same candidate is marked `suppressed` and excluded from automatic/manual eligibility until policy/history changes.

### Test and coverage impact memory

Every repair attempt stores the changed files, executed checks, pass/fail outcome, quality score, and any available coverage signals. Future candidates touching the same files receive historical test-impact context and previously successful checks can be appended to their bounded validation plan.

```text
GET /improvements/test-impact?project_name=...&files=app/foo.py,tests/test_foo.py
```

### Cancellation and discard

```text
POST /improvements/cycles/{cycle_id}/cancel
POST /improvements/cycles/{cycle_id}/experiments/{experiment_id}/discard
```

Cancellation is immediate for paused states and cooperative for an in-flight validation. A verified repair produced while cancellation is pending is revoked once that validation returns. Discarding an experiment revokes its unapplied verified repair.

### Dashboard and VS Code visibility

The project workspace now has an **Improvements** tab for health, cycles, candidate selection, experiment comparison/discard, apply/cancel controls, approved baseline capture, governance results, and versioned policy editing.

The VS Code extension is now version `1.2.0` and adds:

```text
AI Coding Assistant: Improvement Center
AI Coding Assistant: Improve Project
AI Coding Assistant: Cancel Improvement Cycle
```

The manual VS Code flow can observe health, rank candidates, choose one, optionally compare two isolated candidates, stream validation activity, inspect the final state, and explicitly approve the verified winner.

### Frontend packaging repair

The frontend Dockerfile already expected `package.json`, but the repository did not contain one. Part 6 restores the React/Vite/Monaco manifest so the dashboard source has a coherent package definition. Dependency installation was not used as a claimed validation gate for this build because the local npm install attempt exceeded the execution window.

### Part 6 verification baseline

```text
pytest -q
58 passed

python -m compileall -q app tests
PASS

all app.* imports
MODULES 91
IMPORT_FAILURES 0

FastAPI OpenAPI required Part 6 routes
PRESENT

node --check ../vscode-extension/extension.js
PASS

backend security review of Part 6 touched modules
critical 0 / high 0 / medium 0 / low 0
```

See `BUILD_PART_6_REPORT.md` for the implementation and safety details.

## 18. Recommended Part 7

Do not enable a recurring scheduler yet. Next add guarded-autonomy eligibility reporting, approval roles, immutable/signed policy snapshots, real coverage-report delta ingestion, failure-class cooldowns, and cross-cycle regression attribution. Scheduling should only become eligible after enough successful manual outcomes and clean governance history exist.

## 19. Part 7 — Autonomy Readiness, Signed Policy Evidence & Approval Roles

Part 7 implements the evidence gates recommended after Part 6 while keeping recurring scheduling disabled.

New capabilities:

- every cycle snapshots and seals its project policy; `IMPROVEMENT_POLICY_SIGNING_KEY` upgrades this to HMAC-SHA256 signing,
- integrity is rechecked before promotion and mismatches stop in `POLICY_INTEGRITY_BLOCKED`,
- optional authenticated local approval roles with persisted approval evidence but no stored tokens,
- policy-level minimum approvals and required roles,
- coverage.py JSON / generic JSON / Cobertura XML coverage ingestion and deterministic coverage delta APIs,
- failure-class cooldowns,
- historical candidate-risk escalation,
- cross-cycle regression attribution,
- deterministic `safe_to_automate` / `not_safe_to_automate` readiness reports,
- dashboard readiness blockers and verified approval controls,
- VS Code extension `1.3.0` with **Autonomy Readiness** plus approval prompts.

Key APIs:

```text
GET  /improvements/readiness
POST /improvements/coverage/reports
GET  /improvements/coverage/reports
GET  /improvements/coverage/delta
GET  /improvements/regressions
POST /improvements/cycles/{cycle_id}/approve
GET  /improvements/cycles/{cycle_id}/approvals
```

A readiness verdict never enables scheduling or automatic source apply. `scheduler_enabled=false` and `automatic_source_apply_enabled=false` remain explicit in the report.

Part 7 backend verification baseline:

```text
pytest -q
67 passed
```

See `BUILD_PART_7_REPORT.md` for the complete implementation and gate definitions.

## 20. Recommended Part 8

Only after projects repeatedly satisfy the Part 7 readiness gates should a scheduler be introduced, and the first scheduler should be **dry-run / observe-propose only** with maintenance windows, rate limits, leases, kill switch, CI evidence and SLO/error-budget gates. Automatic live source promotion should remain disabled.

## 21. Part 8 — Dry-Run Guarded Scheduler & Evidence Control Plane

Part 8 introduces the first scheduler, but scheduled execution is intentionally restricted to observation/proposal work. It cannot promote live source changes.

New capabilities:

- persistent `observe_propose` and `canary_observe` schedules,
- timezone-aware maintenance windows,
- global + per-project concurrency leases with TTL/heartbeat,
- global/project/schedule rate limits,
- persistent global/project emergency kill switch,
- authenticated and size-bounded CI/webhook evidence ingestion,
- SLO/error-budget evidence and freshness/threshold gates,
- Part 7 readiness as a pre-scheduling gate,
- optional background poller controlled by `IMPROVEMENT_DRY_RUN_SCHEDULER_ENABLED`,
- scheduler status/history/lease APIs,
- dashboard scheduler controls,
- VS Code extension `1.4.0` scheduler commands.

Key APIs:

```text
GET/POST /improvements/scheduler/schedules
POST     /improvements/scheduler/schedules/{schedule_id}/run-now
POST     /improvements/scheduler/tick
GET      /improvements/scheduler/status
GET      /improvements/scheduler/runs
GET      /improvements/scheduler/leases
POST     /improvements/scheduler/kill-switch
POST/GET /improvements/evidence/ci
POST/GET /improvements/evidence/slo
```

A scheduled `observe_propose` run is rewritten to `policy=observe_only`. A `canary_observe` run captures health only and creates no improvement cycle. `scheduled_source_apply_enabled=false` and `automatic_source_apply_enabled=false` remain hard safety invariants.

Part 8 backend verification baseline:

```text
pytest -q
78 passed
```

See `BUILD_PART_8_REPORT.md` for the complete implementation and gate definitions.

## 22. Recommended Part 9

Before considering stronger autonomy, add production-grade scheduler evidence integrity and observability: signed/replay-protected webhooks, commit binding, operator audit identity, metrics/traces/alerts, distributed lease support, schedule simulation/preview, and environment-specific policies. Automatic live source promotion should remain disabled.

## 22. Part 9 — Production-Hardened Dry-Run Scheduler Control Plane

Part 9 hardens Part 8 for multi-instance and production-style operation without enabling automatic source promotion.

### Evidence integrity

CI/SLO evidence may now be authenticated with HMAC-SHA256 using `IMPROVEMENT_EVIDENCE_WEBHOOK_SIGNING_SECRET`. Signed deliveries use:

- `X-Improvement-Signature: sha256=<hex>`
- `X-Improvement-Timestamp: <unix-seconds-or-ISO8601>`
- `X-Improvement-Delivery-ID: <unique-id>`

The signature covers `timestamp.delivery_id.canonical_json_body`. Timestamps are freshness-bounded and delivery IDs are persisted so replays are rejected. The Part 8 token header remains available as a backwards-compatible development fallback when HMAC signing is not configured.

### CI identity binding

Schedules can bind CI evidence to an explicit `ci_branch` and/or `ci_commit_sha`, or set `bind_ci_to_project_head=true` to require CI evidence for the project's current Git HEAD. Mismatched evidence cannot satisfy the CI gate.

### Environment policies

Every schedule now has `environment=dev|staging|prod`.

- `dev`: base interval/safety controls.
- `staging`: readiness + CI + signed evidence + CI identity binding.
- `prod`: staging requirements plus SLO/error-budget evidence, operator registry, and a higher minimum interval.

Environment policy is a blocker only for dry-run scheduling. It never authorizes live source apply.

### Operator identity and audit

Configure `IMPROVEMENT_OPERATOR_CREDENTIALS_JSON` with operator IDs, roles and tokens. When configured, scheduler mutations require `X-Improvement-Operator-ID` and `X-Improvement-Operator-Token`. Create/update/delete, manual tick/run, kill-switch changes and alert acknowledgements are persisted in `improvement_operator_audit`.

### Fenced leases

Part 9 adds a monotonic fencing token per lease key. A stale scheduler worker cannot heartbeat, release or continue using a newer worker's lease generation. This is intended for multiple backend instances sharing the same scheduler database.

### Simulation, alerts and metrics

New APIs:

```text
POST /improvements/scheduler/simulate
GET  /improvements/scheduler/schedules/{schedule_id}/simulate
GET  /improvements/scheduler/metrics
GET  /improvements/scheduler/metrics/prometheus
GET  /improvements/scheduler/telemetry
GET  /improvements/scheduler/alerts
POST /improvements/scheduler/alerts/{alert_id}/ack
GET  /improvements/scheduler/audit
```

Simulation evaluates deterministic gates without creating a scheduler run, lease, improvement cycle or source change. Blocked/error/canary-failed runs create persisted alerts. Scheduler run telemetry is persisted and exposed as JSON and Prometheus text.

### Safety invariant

Part 9 still reports:

```text
scheduled_source_apply_enabled = false
automatic_source_apply_enabled = false
```

No environment, operator role, signed webhook, CI result, SLO result or readiness verdict can bypass the existing manual repair/governance/approval/apply path.

Part 9 backend verification baseline: **88 passing tests**.

## 23. Recommended Part 10

The next layer should focus on deployment integration rather than additional autonomy: optional external alert sinks, real OpenTelemetry exporters, HA database/lease backends, Git provider adapters that bind pull-request/commit provenance, retention/compaction jobs, and disaster-recovery tests. Automatic live source promotion should remain disabled until operational evidence justifies a separate explicit design decision.

## 24. Part 10 — Deployment & Operations Hardening

Part 10 focuses on deploying and operating the Part 9 dry-run scheduler safely rather than increasing autonomy.

New capabilities:

- durable external alert webhook delivery with optional HMAC signatures,
- optional OTLP/HTTP scheduler telemetry export,
- pluggable fenced lease coordination: `sqlite`, optional `redis`, optional `postgres`,
- background scheduler leader election over the configured lease backend,
- native GitHub/GitLab CI provenance adapters with provider authentication and replay protection,
- retention preview and confirmed compaction,
- non-destructive SQLite disaster-recovery drills with integrity check and SHA-256 evidence,
- scheduler operations and DR runbooks,
- dashboard operations controls,
- VS Code extension `1.6.0` integration/HA and DR commands.

Key APIs:

```text
GET  /improvements/scheduler/integrations
POST /improvements/scheduler/integrations/flush
POST /improvements/evidence/github
POST /improvements/evidence/gitlab
GET  /improvements/scheduler/admin/retention/preview
POST /improvements/scheduler/admin/retention/compact
POST /improvements/scheduler/admin/dr-drill
GET  /improvements/scheduler/admin/dr-drills
```

For multi-instance deployments, install `requirements-operations.txt` and select `IMPROVEMENT_SCHEDULER_LEASE_BACKEND=redis` or `postgres`. The default remains SQLite.

Part 10 does not add scheduled source promotion. Leader election only decides which backend instance polls due **dry-run** schedules.

See `BUILD_PART_10_REPORT.md`, `../generated_docs/SCHEDULER_OPERATIONS_RUNBOOK.md`, and `../generated_docs/SCHEDULER_DR_RUNBOOK.md`.

## 25. Part 11 — Deployment Packaging & Integration Reliability

Part 11 turns the Part 10 operations layer into a deployable package. It adds compose profiles for Redis, PostgreSQL, and OpenTelemetry; a file/environment secret provider; exponential delivery backoff and dead-letter handling; GitHub/GitLab commit-status publication; persisted scheduler traces exported to OTLP; production `/health/live` and `/health/ready` probes; DR backup rotation and restore verification; and an HA failover smoke script.

The scheduler remains dry-run only. None of these operational controls authorize scheduled source promotion.


## 26. Part 12 — Candidate-to-Staging Release Orchestration

Part 12 adds a release-control layer above exact verified repairs. It copies the project into an isolated release workspace, applies the verified patch there, runs machine validation and integration/regression checks, optionally performs a fixed-argument Docker build, generates a CycloneDX SBOM and staging manifest, evaluates vulnerability evidence, records expiring preview environments, creates a signed release-evidence bundle, and requires explicit operator confirmation before the candidate becomes `staging_ready`.

The default vulnerability mode is `report_only`; Trivy JSON, Grype JSON, or normalized findings can be uploaded. Optional `trivy` mode can run a local fixed-argument scanner. Artifact/evidence signatures use HMAC-SHA256 when `IMPROVEMENT_RELEASE_SIGNING_KEY` is configured.

The release system has no production-promotion function or API. It also never applies the candidate patch to the live source tree. Scheduled source apply remains disabled.

See `BUILD_PART_12_REPORT.md` and `../generated_docs/PART12_STAGING_RELEASE_RUNBOOK.md`. Verified Part 12 boundary: **121 backend tests**.

## 27. Part 13 — Staging Providers & Production Release Handoff

Part 13 extends a Part 12 `staging_ready` candidate into a staging-only delivery workflow. It can prepare or trigger GitHub Actions/GitLab pipelines, plan or execute staging-only Kubernetes/ECS deployments, promote OCI artifacts into staging destinations, run safe staging smoke/API/E2E checks, generate SLSA-style in-toto provenance, optionally invoke Cosign attestations, and roll back staging deployments/previews.

After a deployment is validated, a verified `release-manager`/`maintainer` can create a **production release request** with explicit confirmation. That request is an auditable evidence handoff only: the backend has no production-deployment route, production target adapter, or automatic production promotion worker.

Key APIs:

```text
GET  /improvements/staging/capabilities
POST /improvements/staging/releases/{release_id}/ci/trigger
POST /improvements/staging/releases/{release_id}/oci/promote
POST /improvements/staging/releases/{release_id}/deployments
POST /improvements/staging/deployments/{deployment_id}/evidence
POST /improvements/staging/deployments/{deployment_id}/tests
POST /improvements/staging/deployments/{deployment_id}/rollback
POST /improvements/staging/previews/{preview_id}/teardown
POST /improvements/staging/releases/{release_id}/attestations/slsa
POST /improvements/staging/releases/{release_id}/attestations/cosign
POST /improvements/staging/releases/{release_id}/production-release-request
GET  /improvements/staging/production-release-requests
```

Direct staging execution and provider-side CI/OCI actions are disabled by default. See `BUILD_PART_13_REPORT.md` and `../generated_docs/PART13_STAGING_PROVIDER_RUNBOOK.md`. Verified Part 13 boundary: **133 backend tests**.


## 28. Part 14 — Production Release Governance

Part 14 starts from the signed Part 13 production release request and adds a separate governance plane. A verified release manager opens a governance case, binds a change ticket and deterministic rollout plan, optionally binds the change to a release train, and collects evidence-bound approvals from distinct operators. By default at least two approvals are required and the `release-manager` and `ops` roles must both be represented.

Approvals are bound to the exact governance digest. If the ticket, rollout plan, release train, or signed Part 13 request changes, older approvals remain in history but no longer count. Configured production freeze windows and release-train controls are re-evaluated before lock/package creation.

Once quorum and all policy gates pass, an authorized release manager can create an immutable HMAC-signed governance lock. Locked governance inputs cannot be edited. An authorized release manager/ops operator can then create a signed **credential-free deployment package** for an independent production deployer.

Key APIs:

```text
GET  /improvements/production-governance/capabilities
GET  /improvements/production-governance/freeze-status
POST /improvements/production-governance/cases
GET  /improvements/production-governance/cases
GET  /improvements/production-governance/cases/{case_id}
POST /improvements/production-governance/cases/{case_id}/change-ticket
POST /improvements/production-governance/cases/{case_id}/rollout-plan
POST /improvements/production-governance/cases/{case_id}/approvals
GET  /improvements/production-governance/cases/{case_id}/approvals
POST /improvements/production-governance/cases/{case_id}/evaluate
POST /improvements/production-governance/cases/{case_id}/lock
POST /improvements/production-governance/cases/{case_id}/deployment-package
POST /improvements/production-governance/release-trains
GET  /improvements/production-governance/release-trains
POST /improvements/production-governance/cases/{case_id}/release-train
GET  /improvements/production-governance/packages/{package_id}
```

Part 14 deliberately has no production deploy/promote endpoint, cloud production adapter, production credential store, or production execution worker. The signed package is intended for a separately operated production deployer.

See `BUILD_PART_14_REPORT.md` and `../generated_docs/PART14_PRODUCTION_GOVERNANCE_RUNBOOK.md`. Verified Part 14 boundary: **145 backend tests**.

## v1.1 product improvement release

Part 16 completed the major architecture roadmap. v1.1 is an optimization release, not Part 17.

Key additions:

- `app/adaptive_orchestration.py`: deterministic task classification and smallest-safe agent route;
- `app/repository_intelligence.py`: bounded local symbol/import/reverse-import/call graph and relevance ranking;
- `app/experience_memory.py`: contextual project-scoped mistake/success memory;
- `app/model_usage.py`: privacy-preserving LLM duration/token-size telemetry;
- `app/v11_evaluation.py`: repair-efficiency and benchmark comparison storage;
- `app/v11_api.py`: inspection/evaluation endpoints under `/v1.1`.

A simple first repair attempt can now skip the Debugger model call; any validation failure escalates to Debugger automatically. Reviewer, Security, Quality, approval, governance, staging, certification, and independent-production-deployer boundaries are unchanged.
