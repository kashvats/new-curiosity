# AI Coding Assistant — VS Code Extension

This extension is the first IDE surface for the local agentic engineering backend. It does not give the LLM direct filesystem or terminal authority: write modes use the backend's isolated candidate workspace, bounded repair loop, machine validation, reviewer/security gates, verified candidate store, snapshot, and post-apply rollback checks.

## Modes

- **Ask** — project-aware Q&A; no writes.
- **Plan** — creates an incremental implementation plan; no writes.
- **Edit** — prepares a small verified patch with a short retry budget.
- **Fix** — diagnose → patch → validate → feed failure back → retry.
- **Review** — independent correctness/security review of the current context; no writes.
- **Agent** — inspect → plan → edit → validate → review → security → verified diff.

Write modes never automatically modify the live workspace. When a candidate is verified, VS Code opens a native diff preview. **Apply Verified Repair** requires explicit confirmation. The backend snapshots the project, applies the exact verified candidate, re-runs its machine checks, and automatically restores the snapshot if the post-apply checks fail.

## Setup

1. Start the FastAPI backend on `http://127.0.0.1:8000` or configure `aiCodingAssistant.backendUrl`.
2. The folder opened in VS Code must correspond to a project available under the backend's configured `WORKSPACE_ROOT` with the same folder name.
3. Package locally with `vsce package`, then install the generated VSIX with **Extensions → … → Install from VSIX**.
4. Open the Command Palette and use `AI Coding Assistant: Ask`, `Plan`, `Edit`, `Fix`, `Review`, or `Agent`.

Use **AI Coding Assistant: Show Agent Activity** to see streamed diagnoses, attempts, validation commands, reviews, security gates, and completion status.

## Part 6 improvement controls

Version `1.2.0` also exposes the manually governed self-improvement controller:

- **AI Coding Assistant: Improvement Center** — health, active policy and recent cycles.
- **AI Coding Assistant: Improve Project** — start manual or observe-only improvement; manual mode lets you choose a candidate, optionally compare two isolated candidates, stream validation/governance events and explicitly approve the verified winner.
- **AI Coding Assistant: Cancel Improvement Cycle** — cancel the latest/current improvement cycle.

These commands do not enable background recurrence. Live project writes still require explicit confirmation and the backend performs a final governance recheck before apply.

## Part 9 scheduler hardening

Version `1.5.0` adds:

- **AI Coding Assistant: Simulate Dry-Run Schedule** — evaluates the selected schedule's gates without creating a run or cycle.
- **AI Coding Assistant: Scheduler Metrics & Alerts** — shows persisted scheduler metrics and open alerts.
- operator credential prompts for manual scheduler tick and emergency-stop changes when the backend operator registry is configured.
- environment, HMAC-webhook, operator-registry and fenced-lease status in the scheduler view.

The extension never stores the operator token. Scheduled and automatic source apply remain disabled.

## Part 10 deployment operations

Version `1.6.0` adds:

- **AI Coding Assistant: Scheduler Integrations & HA** — shows external delivery configuration, HA coordination backend, leader-election state and recent deliveries.
- **AI Coding Assistant: Run Scheduler DR Drill** — creates and validates a point-in-time scheduler database backup without restoring over the live database.
- Part 10 lease backend, leader-election, alert-sink and OTLP-export visibility in scheduler status.

The extension still never stores operator tokens, and scheduled/automatic source apply remain disabled.

## Part 12 — Staging Release Center

Version 1.8.0 adds **AI Coding Assistant: Staging Release Center**. It can inspect candidate-to-staging release capabilities, create a release from the latest verified improvement candidate, run the isolated release pipeline, and explicitly mark a fully-gated candidate staging-ready. There is no production-promotion command.

## Part 13 — Staging Provider & Release Handoff

Version 1.9.0 adds **AI Coding Assistant: Staging Provider & Release Handoff**. It shows Part 13 staging-provider capabilities and release requests, can register an external staging deployment for a `staging_ready` release, and can create a human-authorized production release request after the release is `staging_validated`. The command does not deploy production.


## Part 14 — Production Release Governance

Version 1.10.0 adds **AI Coding Assistant: Production Release Governance**. It can inspect signed Part 13 production release requests, open a governance case, attach a change ticket and rollout strategy, submit evidence-bound approvals, lock an approved case, and create a signed credential-free package for an independent production deployer.

The command does not possess production credentials and has no production deployment action. Changing governance evidence invalidates older approvals, and locked cases are immutable.

## Part 15

Version 1.11.0 adds **Production Outcome Learning** visibility and extends Production Release Governance with immutable artifact binding plus issuance of short-lived deployment authorizations for the separate production-deployer service. The extension still has no direct production-deploy command.


## v1.1 Intelligence & Efficiency

Extension v1.13.0 adds **AI Coding Assistant: Intelligence & Efficiency**. It shows adaptive-routing capability, historical repair-efficiency metrics, privacy-preserving model-usage estimates, and an optional route preview for the current task. Prompt/completion text is not stored by the v1.1 usage telemetry.
