# AI Coding Assistant — Agentic Engineering Workspace

This repository is an AI coding workspace made of four cooperating surfaces:

```text
React dashboard / VS Code extension
              │
              ▼
        FastAPI backend
              │
        Shared agent runtime
              │
   Candidate / verification / approval
              │
        Project workspace

Supporting services: Ollama, Qdrant, SearXNG
```

The long-term goal is a bounded self-improving engineering system: it can inspect software, plan changes, write candidate code, test it, feed failures back to the LLM, retry, independently review/security-check the result, require approval, apply with rollback protection, and learn from outcomes.

It is **not** designed to let an LLM directly and indefinitely rewrite a live project.

## Repository layout

| Path | Purpose |
|---|---|
| `backend/` | FastAPI APIs, agents, repair loop, RAG, scans, jobs, persistence |
| `frontend/` | React dashboard |
| `vscode-extension/` | VS Code coding-agent UI: Ask/Plan/Edit/Fix/Review/Agent, streamed activity, diffs, search |
| `searxng/` | local web-search configuration |
| `generated_docs/` | generated architecture/workflow documentation |
| `docker-compose.yml` | local service orchestration |

## Current implementation status

### Part 1

Built the first safe coding/repair substrate: Agent Registry, Coder, Reviewer, candidate workspace, patch engine, safe command runner, repair-attempt persistence, bounded retry loop, snapshots, and agent APIs.

### Part 2

- restored all active missing backend module contracts,
- repaired document/RAG schema drift,
- added Security, Architecture, and Research agents,
- added quality scoring,
- made Reviewer/Security/Quality rejection feed back into the repair loop,
- added exact verified-candidate persistence and approval/apply APIs,
- strengthened terminal policy beyond executable allowlisting,
- made Qdrant, sentence-transformers, and watchdog optional at import time,
- removed the planner's unnecessary LangGraph dependency,
- changed the old orchestrator to use the shared safe repair flow,
- added vector search with SQLite keyword fallback,
- achieved **21 passing backend tests** and **0 backend-module import failures** in the current environment.

### Part 3

- added persistent IDE sessions + event history,
- added Ask / Plan / Edit / Fix / Review / Agent mode orchestration,
- added SSE streaming of diagnoses, retries, checks and gates,
- upgraded Context Agent with files/import-neighbors/tests/selection/diagnostics/Git/check discovery,
- added automatic targeted + broader regression discovery,
- added post-apply machine verification with automatic snapshot rollback,
- added repository tree, code search and symbol search APIs,
- upgraded the VS Code extension to a real coding-agent surface with native diff preview and explicit verified apply,
- achieved **31 passing backend tests**, **0 backend-module import failures**, and a clean `node --check` for the extension.

### Part 4

- added deterministic unified project-health snapshots,
- added the `improvement` agent (10 shared agent roles total),
- added evidence-backed improvement candidates with benefit/risk/confidence/urgency/cost prioritization,
- added persisted manual improvement cycles and append-only activity events,
- added `manual` and `observe_only` policies while keeping scheduling disabled,
- routed selected improvements through the same isolated recursive repair loop,
- added post-apply health monitoring and persistent outcome memory,
- added rollback when the measured project-health score materially regresses,
- added explicit rollback for already-applied verified repairs,
- achieved **41 passing backend tests** and **0 backend-module import failures**.


### Part 5

- added conservative outcome-aware strategy learning across measured cycles,
- added `WAITING_SELECTION` so ranked candidates can be inspected and explicitly chosen before repair,
- added bounded multi-candidate experiment mode using separate isolated workspaces,
- added cycle-level repair/attempt/file/patch-byte budgets,
- added approved API-contract and architecture-layout baselines with drift detection,
- added offline dependency-health analysis without registry/network lookups,
- expanded project health with dependency and drift dimensions,
- persisted experiment results and exposed strategy-performance statistics,
- kept recurring scheduling disabled and kept explicit human approval mandatory for live apply,
- achieved **49 passing backend tests**, **0 backend-module import failures**, and clean VS Code extension syntax/JSON validation.


### Part 6

- added versioned project-specific improvement governance policies,
- added protected API-contract and architecture-invariant gates over the exact verified patch,
- added a second governance recheck immediately before live apply,
- added repeated-candidate fingerprints and suppression after repeated unsuccessful attempts,
- added historical test/check and coverage-signal impact memory that can enrich future validation plans,
- added cooperative cycle cancellation and experiment discard/revocation,
- automatically revokes governance-blocked and non-winning verified experiment candidates,
- exposed improvement health, cycles, candidate selection, experiments, governance and policy editing in the project dashboard,
- added VS Code Improvement Center / Improve Project / Cancel Improvement commands,
- restored the missing frontend `package.json` expected by its Dockerfile,
- kept recurring scheduling disabled and human approval immutable,
- achieved **58 passing backend tests**, **0 backend-module import failures**, clean OpenAPI registration, and clean VS Code extension syntax/JSON validation.


### Part 7

- added tamper-evident policy snapshots with optional HMAC-SHA256 signing,
- added authenticated local approver roles and persisted approval evidence without storing tokens,
- added policy-required verified approval quorum/role gates before source apply,
- added coverage.py JSON and Cobertura coverage ingestion plus deterministic coverage deltas,
- added failure-class cooldowns and historical candidate-risk escalation,
- added cross-cycle regression attribution,
- added deterministic guarded-autonomy readiness reporting with `safe_to_automate` / `not_safe_to_automate`,
- exposed readiness/approval evidence in the dashboard and VS Code extension 1.3.0,
- kept the scheduler and automatic source promotion disabled,
- achieved **67 passing backend tests**.

For the complete technical description and API examples, read `backend/README.md`.

## Core loop

```text
Detect/request
    ↓
Collect context
    ↓
Debugger / Planner
    ↓
Coder
    ↓
Candidate workspace
    ↓
Machine validation
    ↓ fail ───────────────┐
Reviewer                  │
    ↓ reject ─────────────┤
Security                  │
    ↓ reject ─────────────┤
Quality                   │
    ↓ reject ─────────────┤
Verified                  │
    ↓                     │
Persist exact candidate   │
    ↓                     │
Human approval            │
    ↓                     │
Snapshot + apply          │
                          │
        failure evidence ─┘
               ↓
        next LLM attempt
```

## Start with Docker

```bash
docker compose up --build
```

Typical services:

- Frontend: `http://localhost:3000`
- Backend docs: `http://localhost:8000/docs`
- Qdrant: `http://localhost:6333`

Ollama is expected to run according to your `.env` configuration.

## Backend development

```bash
cd backend
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload
```

Current verified backend baseline:

```text
145 passed
0 backend module import failures
```

### Part 8

- added the first dry-run guarded scheduler control plane,
- added persistent observe/propose and canary schedules,
- forced every scheduled proposal cycle to `observe_only`,
- added maintenance windows, rate limits and concurrency leases,
- added a persistent emergency kill switch,
- added CI/webhook and SLO/error-budget evidence gates,
- added optional background polling (disabled by default),
- exposed scheduler controls in the dashboard and VS Code extension 1.4.0,
- kept scheduled and automatic source apply disabled,
- achieved **78 passing backend tests**.

## Next slice

Part 9 should harden production scheduler operation with signed/replay-protected evidence, commit binding, operator audit identity, telemetry/alerts, distributed leases, schedule simulation and environment-specific policies. Automatic live source promotion should remain disabled.

See `backend/SELF_IMPROVING_ORGANISM_README.md` for the complete staged roadmap.

### Part 9

- added HMAC-SHA256 CI/SLO webhook signatures with timestamp and delivery-ID replay protection,
- added branch/commit and optional current-Git-HEAD binding for CI evidence,
- added authenticated scheduler operator identity and persistent audit history,
- added `dev` / `staging` / `prod` scheduler policies,
- added monotonic fenced leases for safer multi-instance scheduling over a shared database,
- added side-effect-free schedule simulation,
- added persisted blocked/error/canary alerts and acknowledgement,
- added scheduler telemetry plus JSON and Prometheus metrics,
- exposed Part 9 controls in the dashboard and VS Code extension 1.5.0,
- kept scheduled and automatic source apply disabled.

### Part 10

- added a durable external scheduler-alert outbox with optional HMAC-signed HTTPS delivery,
- added optional OTLP/HTTP export for scheduler telemetry,
- added pluggable fenced lease coordination (`sqlite`, optional Redis, optional PostgreSQL),
- added background scheduler leader election,
- added authenticated/replay-protected GitHub and GitLab CI provenance adapters,
- added retention preview/compaction administration,
- added non-destructive disaster-recovery drills with SQLite integrity and SHA-256 verification,
- added operations and DR runbooks,
- exposed Part 10 operations in the dashboard and VS Code extension 1.6.0,
- kept scheduled and automatic source apply disabled.

### Part 11

Part 11 packages the Part 10 control plane for real deployment without increasing autonomy. It adds Redis/PostgreSQL/OTel Docker profiles, file-backed secret resolution, integration retry/dead-letter handling, GitHub/GitLab commit-status publishing, structured scheduler traces with OTLP export, production liveness/readiness probes, DR backup rotation/restore verification, and HA failover test tooling. Scheduled source apply remains disabled.


### Part 12

- added candidate-to-staging release orchestration over exact verified repairs,
- applies candidate patches only inside isolated TTL release workspaces, never the live source tree,
- added first-class validation/integration-test release evidence,
- added optional fixed-argument container builds with Docker networking disabled by default,
- generates CycloneDX 1.5 SBOMs, signed staging manifests and signed release-evidence bundles,
- added Trivy/Grype/generic vulnerability evidence normalization and threshold gates,
- added expiring external preview-environment records,
- reuses GitHub/GitLab status publication for staging-readiness checks,
- added explicit operator-confirmed `candidate → staging_ready` promotion,
- added dashboard staging-release controls and VS Code extension 1.8.0 Staging Release Center,
- deliberately provides **no production promotion API**,
- achieved **121 passing backend tests**.

See `backend/BUILD_PART_12_REPORT.md` and `generated_docs/PART12_STAGING_RELEASE_RUNBOOK.md`.

### Part 13

- adds staging-only GitHub Actions and GitLab pipeline adapters,
- adds external/Kubernetes/ECS staging deployment providers with direct execution disabled by default,
- adds staging OCI artifact promotion with production-target denial,
- adds safe smoke/API/E2E staging validation,
- generates in-toto/SLSA-style provenance and optional Cosign OCI attestations,
- adds staging rollback and preview teardown,
- adds an explicit verified-operator `staging_validated → production release request` handoff,
- deliberately provides **no production deployment route or worker**,
- upgrades the VS Code extension to **1.9.0**,
- achieves **133 passing backend tests**.

See `backend/BUILD_PART_13_REPORT.md` and `generated_docs/PART13_STAGING_PROVIDER_RUNBOOK.md`.


### Part 14

- adds a separate production release governance plane above Part 13 release requests,
- adds evidence-bound multi-person approvals with distinct operators and required-role quorum,
- adds change-ticket/Jira-style references, configurable freeze windows and release trains,
- generates deterministic canary, blue-green, or rolling rollout plans without executing them,
- adds immutable signed release locks that prevent post-approval governance input changes,
- creates signed, credential-free deployment packages for an independent production deployer,
- stores no production deployment credentials and exposes no production deployment executor,
- upgrades the VS Code extension to **1.10.0** with Production Release Governance controls,
- achieves **145 passing backend tests** across the full regression set.

See `backend/BUILD_PART_14_REPORT.md` and `generated_docs/PART14_PRODUCTION_GOVERNANCE_RUNBOOK.md`.

## Part 15 — Independent Production Deployer & Production Outcome Learning

Part 15 introduces a deliberately separate `production-deployer/` trust boundary. The AI backend still cannot deploy production and receives no production credentials. It binds the exact immutable artifact, issues a short-lived single-use signed authorization, and hands the Part 14 package to the deployer. The deployer verifies the package/lock/quorum/artifact/authorization, applies SLO gates and rollback behavior, and emits a signed terminal receipt.

Those signed production outcomes are fed back into the improvement-learning system. Strategies that succeed in production gain evidence; strategies that fail or cause rollbacks are penalized and risk-escalated for later proposals. This is **persistent operational learning, not model-weight retraining**.

See `backend/BUILD_PART_15_REPORT.md`, `generated_docs/PART15_PRODUCTION_DEPLOYER_RUNBOOK.md`, and `production-deployer/README.md`.

## Part 16 — Production hardening and v1.0 readiness certification

Part 16 adds a signed production-readiness certification plane and independent-deployer hardening. Certification requires fresh operator-recorded evidence across deployer tests, migration safety, key rotation, SLO windows, rollback drills, chaos/failover, security attack testing, audit-chain verification, and load/concurrency checks. The AI backend still cannot execute production deployments.
