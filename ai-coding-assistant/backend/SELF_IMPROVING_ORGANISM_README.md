# Self-Improving Engineering Organism — Assembly & Feature Roadmap

## 1. Goal

Turn the existing AI Coding Assistant into a **bounded self-improving engineering system** that can inspect a project, identify weaknesses, propose improvements, validate them, learn from outcomes, and repeat — **only within the machine, models, permissions, tools, and safety limits that are actually available**.
This is not intended to be an unrestricted self-modifying process. The system should improve through a controlled feedback loop:
**Observe → Understand → Diagnose → Prioritize → Propose → Validate → Approve → Apply → Measure → Remember → Repeat**
The same loop can eventually be aimed at the assistant's own codebase, but self-changes should use the same test, approval, backup, and rollback gates as changes to any other project.

---

## 2. What Already Exists

The repository already contains useful building blocks:

- FastAPI backend and React frontend.
- Local Ollama model support plus optional OpenAI/Anthropic model paths.
- Hardware profiling using CPU/RAM information.
- Planner based on LangGraph.
- Tool-using agent loop.
- Workspace file tools.
- Project watcher.
- Background jobs and event dispatch.
- SQLite run/job/history storage.
- Qdrant vector database.
- PDF ingestion, OCR, chunking, embeddings, and retrieval.
- Knowledge bases, web summaries, and manual notes.
- Codebase indexing and symbol extraction.
- Architecture understanding.
- Impact analysis.
- Project auditing.
- Test planning, generation, and execution modules.
- Hybrid security scanning.
- Performance scanning.
- Browser automation.
- SearXNG web search.
- Model manager and local model management.
- Run history and error-memory tables.

These pieces mean the system does **not** need to be rebuilt from zero. The main job is to connect them into a reliable closed loop.

---

## 3. Critical Problems To Repair First

Before adding more autonomy, the current foundation needs to be made internally consistent.

### P0 — Broken/missing execution modules

Several active code paths import modules that are not included in the uploaded project:

- `app.coder`
- `app.apply_changes`
- `app.qdrant_service`
- `app.search`
- `app.knowledge_gap_detection`
- `app.rag_eval`
- `app.regression_detection`
- `app.change_timeline`

This currently breaks parts of:

- Orchestrator execution.
- Audit-to-fix workflow.
- Session resume.
- Document indexing.
- RAG evaluation.
- Knowledge-gap jobs.
- Regression jobs.
- Backup/restore timeline integration.

**First implementation target:** restore or replace these contracts before introducing self-improvement scheduling.

### P0 — Unsafe command execution

`workspace_tools.py` and `test_runner.py` currently contain shell-based execution paths. The self-improving loop should never be allowed to turn arbitrary LLM text directly into unrestricted shell execution.
Replace with:

- command allowlists,
- argument arrays (`shell=False`),
- workspace confinement,
- timeouts,
- environment filtering,
- output limits,
- explicit approval for destructive actions.

### P0 — Reliable rollback

Backups are referenced, but the improvement loop requires a first-class change transaction:

1. Snapshot candidate files.
2. Generate patch.
3. Apply in isolated candidate workspace.
4. Run validations.
5. Promote only after passing gates.
6. Roll back automatically on post-apply regression.

---

# 4. Feature List We Are Going To Improve

## Phase 1 — Foundation Reliability

### 1. Capability Registry

Create one source of truth describing what this installation can actually do.
Track:

- available LLMs,
- context limits,
- CPU/RAM,
- GPU availability if detectable,
- available scanners,
- test frameworks,
- browser availability,
- Qdrant health,
- SearXNG health,
- Docker availability,
- writable workspace paths,
- allowed commands,
- online/offline status.

The planner must consult this registry before creating a plan.

### 2. Model Router Based on Hardware + Task

Use `hardware_context.py` and `model_manager.py` together instead of using static model settings everywhere.
Examples:

- small model for classification and triage,
- coder model for patches,
- stronger model only for high-complexity architecture decisions,
- one concurrent local inference on low-resource machines,
- higher concurrency only when memory permits.

### 3. Repair the Planner → Coder → Reviewer → Tester → Applier Pipeline

The repository already tries to implement this flow, but some modules are absent.
Target contract:
`request -> plan -> inspect -> draft patch -> impact review -> test -> security review -> approval -> apply -> post-check`
Every stage should return structured data and an explicit status.

### 4. Safe Patch Engine

Do not overwrite complete files blindly.
Add:

- unified diff generation,
- expected-old-content checks,
- conflict detection,
- path validation,
- patch-size limits,
- forbidden-path rules,
- backup before apply.

### 5. Change Transaction + Restore Point

Every accepted improvement becomes a transaction containing:

- request,
- plan,
- files changed,
- patch,
- tests before,
- tests after,
- quality score before,
- quality score after,
- backup reference,
- rollback status.

---

## Phase 1B — AI Coding IDE / Claude-Code-Style Workspace

The self-improving backend should also expose a complete coding workflow, not only audits and autonomous repair. The preferred first surface is the existing VS Code extension, backed by the same FastAPI services used by the autonomous loop. A browser IDE using Monaco can be added later without changing the backend contracts.

### Coding IDE features

- Repository tree and fast file search.
- Symbol / definition / reference navigation.
- Context-aware chat about the current project, file, selection, errors, and terminal output.
- `Ask`, `Plan`, `Edit`, `Fix`, and `Agent` modes.
- Generate new files and edit existing files.
- Multi-file edits using patches rather than blind file replacement.
- Inline diff preview with accept/reject per hunk.
- Explain selected code.
- Refactor selected code or a module.
- Generate tests for selected code or changed files.
- Diagnose compiler, linter, test, runtime, and terminal errors.
- Run approved terminal commands, tests, linters, scanners, and builds.
- Automatic project context collection from imports, symbols, tests, architecture, Git diff, memory, and project rules.
- Git status, diff, branch, commit, restore, and rollback support.
- Session history so the agent can resume an unfinished coding task.
- Checkpoints before every agent-generated write.
- Human approval controls for writes and destructive commands.
- Hardware-aware model selection through the shared capability registry.
- A visible activity timeline showing what the agent read, changed, ran, and verified.

### Recommended IDE architecture

```
VS Code Extension / Future Monaco Web IDE
                |
                v
         FastAPI Coding API
                |
      +---------+----------+
      |         |          |
      v         v          v
 Context    Agent Loop   Patch Engine
 Builder                 + Checkpoints
      |         |          |
      +---------+----------+
                |
                v
      Tests / Linters / Security
                |
                v
        Verification Loop
```

The IDE and the autonomous organism must use the **same planner, coder, reviewer, patch, testing, memory, capability, and rollback services**. This prevents two separate coding systems from drifting apart.

---

## Phase 2 — Observation & Diagnosis

### 6. Unified Project Health Snapshot

Combine the existing scanners into one normalized health report.
Inputs:

- architecture scan,
- impact analysis,
- test status,
- coverage,
- security findings,
- performance findings,
- dependency health,
- code quality,
- RAG/index health,
- runtime errors,
- recent failed agent runs.

Output example:

```
{
  "health_score": 78,
  "security": 84,
  "tests": 55,
  "performance": 90,
  "architecture": 80,
  "knowledge": 72,
  "top_improvement_candidates": []
}
```

### 7. Failure Memory

The database already has an `error_memory` table. Turn it into a real learning mechanism.
Remember:

- command/tool failure,
- root cause,
- patch attempted,
- whether it worked,
- project type,
- relevant stack/version,
- confidence,
- last verified date.

Before retrying a similar problem, retrieve prior successful fixes.

### 8. Outcome Memory

Store what happened after every applied change.
Examples:

- test count improved,
- warnings reduced,
- latency improved,
- vulnerability removed,
- regression introduced,
- user reverted change.

The system should learn **which kinds of changes actually help**, not merely which changes were generated.

### 9. Knowledge Gap Detector

Detect when the agent is missing necessary information.
Examples:

- framework version unknown,
- API behavior uncertain,
- undocumented project convention,
- missing architecture context,
- stale dependency documentation.

Then resolve gaps using, in order:

1. project files,
2. local knowledge base,
3. official docs knowledge,
4. web search only if permitted.

### 10. Regression Detector

After every change compare against a baseline:

- tests,
- API contracts,
- import graph,
- security findings,
- performance,
- startup health,
- key browser flows.

No improvement is considered successful if it improves one metric while silently breaking a protected metric.

---

## Phase 3 — Improvement Brain

### 11. Improvement Candidate Generator

Turn observations into small actionable candidates.
Each candidate should contain:

- problem,
- evidence,
- proposed improvement,
- files likely affected,
- estimated benefit,
- estimated risk,
- estimated compute cost,
- validation plan,
- rollback plan.

### 12. Improvement Prioritizer

Rank candidates instead of trying to fix everything.
Suggested score:
`priority = benefit × confidence × urgency / (risk × cost)`
Also enforce:

- one change theme per iteration,
- maximum files per iteration,
- maximum token/compute budget,
- stop if health is already acceptable.

### 13. Experiment Mode

Generate multiple candidate approaches without applying all of them.
For example:

- Candidate A: minimal patch.
- Candidate B: refactor.
- Candidate C: configuration-only fix.

Evaluate each in an isolated workspace and select the best validated result.

### 14. Quality Scorer

An improvement must have a measurable score.
Possible dimensions:

- correctness,
- tests,
- maintainability,
- security,
- performance,
- architecture consistency,
- documentation,
- resource cost.

The system should reject candidate changes whose total score does not beat the baseline by a configurable margin.

### 15. Critic / Reviewer Agent

Use a separate review pass that did not generate the patch.
Reviewer responsibilities:

- verify requirement coverage,
- challenge assumptions,
- inspect risky changes,
- compare patch against architecture and project rules,
- reject unnecessary complexity,
- confirm tests actually validate the requested behavior.

---

## Phase 4 — Controlled Self-Improvement Loop

### 16. Improvement Cycle Controller

This is the heart of the organism.
State machine:
`IDLE -> OBSERVING -> DIAGNOSING -> PROPOSING -> VALIDATING -> WAITING_APPROVAL -> APPLYING -> MONITORING -> LEARNING -> IDLE`
Failure states:
`VALIDATION_FAILED`, `ROLLBACK_REQUIRED`, `BLOCKED_BY_CAPABILITY`, `BUDGET_EXCEEDED`

### 17. Human Approval Modes

Support three policies:

- **Manual** — every source-code change requires approval.
- **Guarded** — low-risk changes can auto-apply; medium/high risk require approval.
- **Observe-only** — system learns and recommends but never writes code.

Default should be **Manual**.

### 18. Self-Target Protection

If the target project is this AI assistant itself:

- never modify the currently running copy directly,
- create an isolated candidate copy/worktree,
- run startup checks against the candidate,
- run tests/scanners,
- require explicit promotion,
- retain the previous working version.

### 19. Automatic Stop Conditions

The loop must stop when:

- tests cannot run,
- model repeatedly fails,
- rollback fails,
- resource usage crosses configured threshold,
- same failure repeats N times,
- candidate score is not improving,
- required capability is missing,
- user approval is required,
- improvement budget is reached.

### 20. Improvement Scheduler

Triggers can include:

- manual request,
- file changes,
- repeated runtime errors,
- failed tests,
- new security finding,
- scheduled health audit,
- dependency update,
- new documentation added.

Do **not** continuously run local LLMs when nothing has changed.

---

## Phase 5 — Learning & Adaptation

### 21. Prompt/Strategy Performance Tracking

Measure strategies by task type.
Track:

- model used,
- prompt template,
- task category,
- success/failure,
- retries,
- latency,
- tokens if available,
- user acceptance/revert.

Use this to select better strategies later.

### 22. Adaptive Tool Selection

The agent should learn a preferred workflow from validated history.
Example:
For a Python import error it may learn that:
`read traceback -> inspect changed module -> inspect imports -> run targeted test`
works better than starting with a full architecture scan.

### 23. Dynamic Context Builder

Instead of sending entire projects to the model, compose context from:

- changed file,
- import neighbors,
- relevant tests,
- architecture summary,
- project rules,
- retrieved memory,
- relevant documentation.

This is especially important for small local models.

### 24. Confidence Calibration

Record whether high-confidence recommendations were actually successful.
If a strategy is frequently wrong, reduce its future confidence and require stronger validation.

### 25. Learning From Reverts

A reverted change is a powerful negative signal.
Record:

- what was reverted,
- why,
- which model/strategy created it,
- which validation failed to catch the problem.

Use this data to tighten future gates.

---

# 5. Suggested Features After The Core Loop Works

These are useful additions, but they should **not** come before the foundation above.

### A. Git Integration

Create branches/commits for candidate changes and use commit hashes as restore points.

### B. Canary Runtime

Start a candidate backend on a temporary port and test it before promotion.

### C. API Contract Snapshotting

Save OpenAPI/API response contracts and detect breaking changes automatically.

### D. Dependency Intelligence

Detect outdated/vulnerable dependencies and propose version-aware upgrade plans.

### E. Automatic Test Gap Generation

Use impact analysis + coverage to generate tests for changed but uncovered behavior.

### F. Architecture Drift Detection

Compare current structure with the last accepted architecture map and flag accidental coupling.

### G. Performance Baseline Laboratory

Keep comparable benchmark runs for endpoints/functions instead of isolated performance findings.

### H. Multi-Agent Debate For High-Risk Changes

Use Architect, Implementer, Reviewer, and Tester roles only for high-risk tasks to avoid unnecessary compute.

### I. Curiosity / Backlog Engine

Maintain a bounded queue of improvement questions such as:

- Why does this job fail repeatedly?
- Which module has the highest change frequency?
- Which code has no tests?
- Which knowledge is stale?

It should never turn curiosity directly into code changes without the normal gates.

### J. Resource Governor

Set per-cycle limits for:

- wall-clock time,
- LLM calls,
- concurrent scans,
- CPU load,
- RAM use,
- browser sessions,
- candidate count.

### K. Project-Specific Policy Files

Support a file such as `.ai-project-rules.yml` containing:

- protected paths,
- required tests,
- allowed commands,
- forbidden dependencies,
- style conventions,
- risk thresholds,
- approval policy.

### L. Improvement Dashboard

Show:

- health score trend,
- active candidate,
- reason for candidate,
- validation results,
- last successful improvement,
- failed/reverted improvements,
- model/tool performance,
- resource usage.

---

# 6. How To Assemble The Parts

## Layer 1 — Capability Layer

Existing pieces:

- `app/hardware_context.py`
- `app/model_manager.py`
- `app/project_rules.py`
- `app/browser_control.py`
- `app/web_search.py`
- `app/workspace_tools.py`

Add:

- `app/capabilities.py`
- `app/resource_governor.py`
- `app/policy_engine.py`

Purpose: decide what actions are possible and permitted before planning.

---

## Layer 2 — Observation Layer

Existing pieces:

- `app/watcher.py`
- `app/architecture.py`
- `app/impact_analysis.py`
- `app/project_auditor.py`
- `app/qa_scanner.py`
- `app/hybrid_scanner.py`
- `app/performance_scanner.py`
- `app/codebase_indexing.py`
- `app/run_history.py`

Add:

- `app/health_snapshot.py`
- `app/regression_detection.py`
- `app/knowledge_gap_detection.py`

Purpose: convert raw project state into evidence.

---

## Layer 3 — Memory Layer

Existing pieces:

- `app/memory_store.py`
- `app/memory_api.py`
- SQLite history tables.
- Qdrant.

Add:

- improvement history,
- experiment history,
- failure-to-fix links,
- baseline metrics,
- strategy statistics.

Purpose: preserve validated experience across runs.

---

## Layer 4 — Reasoning Layer

Existing pieces:

- `app/planner.py`
- `app/agent_loop.py`
- architecture + impact context.

Restore/add:

- `app/coder.py`
- `app/reviewer.py`
- `app/improvement_candidates.py`
- `app/improvement_prioritizer.py`
- `app/quality_scorer.py`

Purpose: decide what should change and why.

---

## Layer 5 — Execution Layer

Existing pieces:

- `app/test_planner.py`
- `app/test_generator.py`
- `app/test_runner.py`
- `app/job_service.py`
- `app/events.py`

Restore/add:

- `app/apply_changes.py`
- `app/change_timeline.py`
- `app/candidate_workspace.py`
- `app/rollback.py`

Purpose: safely validate and apply proposed changes.

---

## Layer 6 — Organism Controller

Add:

- `app/improvement_loop.py`
- `app/improvement_api.py`
- `app/repair_loop.py` — bounded detect → LLM → patch → verify → retry engine.
- `app/repair_attempt_store.py` — persists every attempt and failure signature.
- `app/verification_service.py` — targeted checks followed by protected regression checks.

The controller should only orchestrate existing services. It should **not** contain scanner logic, model logic, or patch logic itself.
Pseudo-flow:

```
start_cycle(project)
    |
    v
load_policy + capabilities + hardware
    |
    v
capture_baseline_health
    |
    v
detect_top_problems
    |
    v
retrieve_relevant_memory
    |
    v
generate_small_improvement_candidates
    |
    v
rank_candidates
    |
    v
create isolated candidate workspace
    |
    v
generate patch
    |
    v
impact review + static checks + tests + security + performance
    |
    +---- fail ---> capture failure evidence ---> send back to LLM
    |                                      |
    |                                      v
    |                              generate revised patch
    |                                      |
    |                         retry while budget remains
    |                                      |
    |                  max retries --------+----> store failure + escalate/discard
    |
    v
compare candidate score vs baseline
    |
    +---- no gain --> discard candidate
    |
    v
approval gate
    |
    v
backup + apply/promote
    |
    v
post-apply regression checks
    |
    +---- regression --> rollback + negative memory
    |
    v
store successful outcome + new baseline
```

---

## 6.1 Recursive Issue-Fix-Verify Loop

When an issue is detected, the system should not make one LLM call and stop. It should run a bounded feedback loop where **verification evidence becomes the next LLM input**.
Core loop:

```
DETECT ISSUE
    |
    v
COLLECT EVIDENCE
(error, failing test, logs, relevant files, recent diff, environment)
    |
    v
SEND TO LLM
    |
    v
LLM RETURNS DIAGNOSIS + PATCH + VALIDATION PLAN
    |
    v
APPLY PATCH IN CANDIDATE WORKSPACE
    |
    v
RUN TARGETED CHECKS
    |
    +---- PASS ----> RUN BROADER REGRESSION CHECKS
    |                         |
    |                         +---- PASS ----> SCORE + APPROVE/APPLY + REMEMBER SUCCESS
    |                         |
    |                         +---- FAIL ----> COLLECT NEW FAILURE EVIDENCE
    |
    +---- FAIL ----> COLLECT NEW FAILURE EVIDENCE
                              |
                              v
                    SEND BACK TO LLM
                              |
                              v
                    GENERATE NEXT FIX
                              |
                              +------> repeat
```

### The next LLM call must receive the previous attempt

Do not ask the model to solve the problem again from scratch. Supply:

- original issue,
- previous diagnosis,
- previous patch,
- exact validation command,
- exact failure output,
- changed files,
- current diff,
- relevant source/test snippets,
- environment/capability information,
- prior failed strategies from memory.

This lets the model reason: **"my previous fix produced this new result; adjust only what is necessary."**

### Suggested algorithm

```
def repair_issue(issue, max_attempts=5):
    baseline = capture_baseline(issue.project)
    context = collect_issue_context(issue)
    previous_attempts = []

    for attempt_no in range(1, max_attempts + 1):
        proposal = llm_fix(
            issue=issue,
            context=context,
            previous_attempts=previous_attempts,
        )

        candidate = create_candidate_workspace(baseline)
        apply_patch(candidate, proposal.patch)

        targeted = run_targeted_validation(candidate, proposal.validation_plan)
        if not targeted.passed:
            previous_attempts.append(
                build_attempt_record(proposal, targeted)
            )
            context = refresh_context(candidate, targeted)
            continue

        regression = run_regression_checks(candidate, baseline)
        if not regression.passed:
            previous_attempts.append(
                build_attempt_record(proposal, regression)
            )
            context = refresh_context(candidate, regression)
            continue

        score = compare_quality(candidate, baseline)
        if not score.acceptable:
            previous_attempts.append(
                build_attempt_record(proposal, score)
            )
            context = refresh_context(candidate, score)
            continue

        return promote_or_request_approval(candidate, proposal, score)

    return escalate_with_full_attempt_history(issue, previous_attempts)
```

### Loop rules

- Default maximum attempts: **3–5**, configurable per policy.
- Every iteration must create a structured attempt record.
- Repeated identical patches or identical failures should stop the loop early.
- The model must not broaden scope automatically after every failure.
- Prefer targeted tests first, then broader regression tests.
- A candidate workspace is reset or cleanly rebased between incompatible attempts.
- Live project files are not modified during retries.
- If the fix requires a destructive operation, missing permission, unavailable tool, or unsupported hardware, mark the issue `BLOCKED` instead of retrying.
- If confidence decreases across attempts, escalate to a stronger model if the capability registry permits it.
- If no stronger model/capability is available, return the complete failure history to the user.

### Model escalation example

```
Attempt 1: fast/small coding model
    ↓ failed
Attempt 2: same model + failure feedback
    ↓ failed differently
Attempt 3: stronger coding/reasoning model + full attempt history
    ↓
pass -> regression -> apply
fail -> stop/escalate to human
```

### Issue states

```
DETECTED
  -> ANALYZING
  -> FIX_PROPOSED
  -> PATCHED_CANDIDATE
  -> VERIFYING
  -> RETRY_REQUIRED
  -> ANALYZING ...

Success:
  -> VERIFIED
  -> WAITING_APPROVAL / AUTO_APPROVED
  -> APPLIED
  -> MONITORED
  -> RESOLVED

Failure:
  -> BLOCKED
  -> MAX_RETRIES_REACHED
  -> ROLLED_BACK
  -> NEEDS_HUMAN
```

### What counts as "fixed"

A passing LLM response is irrelevant. The issue is fixed only when machine-verifiable checks succeed, for example:

- originally failing test passes,
- related tests pass,
- application starts successfully,
- expected API behavior is observed,
- linter/type checker does not introduce new errors,
- security scan does not introduce a regression,
- protected baseline checks remain healthy.

This recursive repair loop should be shared by **IDE Fix mode**, **Agent mode**, **audit auto-fix**, and the **self-improvement controller**.

---

# 7. Proposed New Data Tables

## `improvement_cycles`

- `id`
- `project_name`
- `trigger`
- `state`
- `baseline_score`
- `final_score`
- `selected_candidate_id`
- `started_at`
- `completed_at`
- `stop_reason`

## `improvement_candidates`

- `id`
- `cycle_id`
- `problem`
- `evidence_json`
- `proposal`
- `risk`
- `benefit`
- `confidence`
- `estimated_cost`
- `status`

## `change_transactions`

- `id`
- `candidate_id`
- `patch_json`
- `backup_ref`
- `tests_before_json`
- `tests_after_json`
- `score_before`
- `score_after`
- `approval_status`
- `apply_status`
- `rollback_status`

## `repair_attempts`

- `id`
- `cycle_id` / `issue_id`
- `attempt_no`
- `model`
- `diagnosis`
- `patch_json`
- `validation_plan_json`
- `validation_result_json`
- `failure_signature`
- `quality_score`
- `created_at`

This table is essential for feeding previous failures back into the next LLM iteration and for preventing repeated ineffective fixes.

## `strategy_stats`

- `strategy_key`
- `task_type`
- `model`
- `attempts`
- `successes`
- `reverts`
- `avg_duration_ms`
- `last_used_at`

---

# 8. Minimum Viable Self-Improving Loop

Do not try to implement the entire roadmap at once.
The first usable version should do only this:

1. User selects a project.
2. System reads capability profile.
3. System takes a health snapshot.
4. System chooses **one** low/medium-risk problem.
5. System retrieves related memory/context.
6. Planner creates a small plan.
7. Coder creates a patch in an isolated candidate workspace.
8. Impact analysis runs.
9. Targeted tests/security checks run.
10. If validation fails, the failure evidence + previous patch are sent back to the LLM and steps 7–9 repeat within the retry budget.
11. When targeted checks pass, broader regression checks run.
12. If regression checks fail, feed that evidence back to the LLM and retry.
13. Quality scorer compares before/after.
14. User approves.
15. System creates backup and applies change.
16. Post-apply checks run.
17. If post-apply checks fail, rollback and store negative memory.
18. Outcome and all repair attempts are stored for future cycles.

Once this works reliably, add automated scheduling, experiments, adaptive strategy selection, and optional guarded auto-apply.

---

# 9. Recommended Implementation Order

1. **Fix missing module contracts and broken imports.**
2. **Harden command/test execution.**
3. **Build safe patch + restore transaction.**
4. **Create capability registry and resource governor.**
5. **Create unified health snapshot.**
6. **Implement regression detector.**
7. **Activate failure/outcome memory.**
8. **Build improvement candidate generator + prioritizer.**
9. **Create isolated candidate workspace.**
10. **Add quality scoring.**
11. **Build improvement loop state machine.**
12. **Add approval API/UI.**
13. **Add learning statistics.**
14. **Add scheduling only after manual cycles are stable.**
15. **Allow self-targeting only after rollback/canary behavior is proven.**

---

# 10. Definition Of "Self-Improving" For This Project

The system qualifies as self-improving when it can:

- observe measurable weaknesses,
- select an improvement using evidence,
- propose a bounded change,
- validate the change independently,
- reject failed changes,
- safely apply approved successful changes,
- detect and roll back regressions,
- record the outcome,
- use past outcomes to make better future decisions.

Simply allowing an LLM to rewrite its own source code is **not** self-improvement. The improvement comes from the feedback, validation, memory, and selection loop.

---

# 11. Initial Success Criteria

Before enabling recurring autonomous cycles, require:

- zero unresolved imports in active core workflows,
- reliable candidate workspace isolation,
- tests can run without arbitrary shell execution,
- every code application has a restorable backup,
- baseline and candidate scores are reproducible,
- failed candidates never alter the live project,
- a post-apply regression triggers rollback,
- repeated failures are remembered,
- resource limits are enforced,
- the user can inspect why a change was proposed.

---

# 12. Current Recommendation

The next coding phase should **not** start with an autonomous infinite loop.
Start by restoring the missing core contracts and create one complete, manually-triggered improvement cycle. Once one cycle can safely improve a project, prove the result, roll back on failure, and remember the outcome, then add recurrence and deeper autonomy.
---

# 13. Implementation Progress — Part 1 (2026-09-15)

The first implementation slice is now built. It intentionally focuses on the stable substrate needed by IDE Agent mode and the recursive self-repair loop before adding autonomous scheduling.

## Implemented in Part 1

- `app/capabilities.py` — deterministic runtime capability profile.
- `app/agent_runtime.py` — shared agent registry and Context, Planner, Coder, Debugger, Tester, Reviewer roles.
- `app/coder.py` — restored missing coder contract with structured JSON output, context limits, session persistence, and bounded change validation.
- `app/reviewer.py` — independent LLM review pass.
- `app/candidate_workspace.py` — isolated temporary candidate copies.
- `app/patch_engine.py` — path confinement, create/modify validation, stale-content SHA-256 guard, payload limits, and unified diff previews.
- `app/safe_commands.py` — allowlisted `shell=False` verification commands with workspace confinement, filtered environment, timeout, and output caps.
- `app/verification_service.py` — machine-verifiable validation plan executor.
- `app/repair_attempt_store.py` — persistent attempt/failure history.
- `app/repair_loop.py` — bounded diagnose → code → patch candidate → verify → feed failure back → retry loop.
- `app/apply_changes.py` — restored apply/snapshot contract with automatic restore on apply failure.
- `app/agents_api.py` — `/agents`, `/agents/run`, and `/agents/repair` API surface.
- Existing `/projects/audit/fix/apply` now routes through the shared snapshot/safe-apply engine rather than blind writes.
- Existing config now exposes compatibility aliases for older lowercase setting names while the codebase is migrated incrementally.
- `get_effective_model(role)` now has role-specific model routing rather than returning one model for every task.
- Missing Test Generator router restored.
- Impact API no longer fails registration merely because optional `sentence_transformers` is unavailable at import time.
- Database schema now includes `repair_attempts`, `improvement_cycles`, `improvement_candidates`, and `change_transactions`.

## Verified behavior

Focused automated tests verify:

1. Core agent roles are registered.
2. Candidate workspaces do not modify the live source tree.
3. Path traversal is rejected.
4. Stale-file writes are rejected.
5. Diff preview and safe application work.
6. Agent commands are executable-allowlisted.
7. New persistence tables initialize successfully.
8. A simulated repair attempt fails validation, feeds the failure into the next cycle, passes on the second attempt, and still leaves the live project untouched until explicit application.

## Deliberately deferred to Part 2+

- Remaining legacy missing contracts: `search`, `qdrant_service`, `knowledge_gap_detection`, `rag_eval`, `regression_detection`, `change_timeline`.
- Full Context Builder using symbol/import graph + memory retrieval.
- Test/lint command auto-discovery per project type.
- Security Agent and Architecture Agent as first-class runtime agents.
- Quality scoring and before/after baseline comparison.
- Approval transaction API that promotes a verified repair by `issue_id`.
- Git worktree/branch candidate mode.
- IDE streaming/events and VS Code UI integration.
- Improvement candidate generation/prioritization.
- Recurring autonomous self-improvement scheduler.

The next recommended implementation slice is: **restore legacy contracts → add richer project-aware verification → add Security/Architecture agents → implement verified-candidate approval transaction → then expose the workflow to the IDE UI.**

---

# 14. Implementation Progress — Part 2 (2026-09-15)

Part 2 focused on stability and closing the loop around already-verified code rather than starting recurring autonomy.

## Completed

- Restored `search`, `qdrant_service`, `knowledge_gap_detection`, `rag_eval`, `regression_detection`, and `change_timeline` source contracts.
- Repaired document/chunk SQLite schema drift across old and newer ingestion modules.
- Added lazy optional loading for Qdrant and sentence-transformers.
- Made watchdog optional instead of a backend import blocker.
- Removed the simple planner's hard dependency on LangGraph.
- Added Security, Architecture, and Research agents; registry now exposes nine roles.
- Added deterministic security review and candidate quality scoring.
- Reviewer/Security/Quality rejection now becomes recursive repair evidence.
- Hardened command policy beyond executable allowlisting (blocks `python -c`, mutating Git, path escapes, unsupported npm scripts).
- Added protected patch paths.
- Added exact verified-candidate persistence and explicit approval/apply endpoints.
- Old orchestrator now uses the shared repair loop instead of direct LLM-to-live-code application.
- Added `/search` with vector retrieval and SQLite keyword fallback.
- All backend Python modules import successfully in the current environment.
- Automated suite: **21 passing tests**.

## Updated next recommendation

Part 3 should now move upward into the developer experience while keeping the same backend contracts:

1. project-aware validation discovery,
2. import/symbol/test/Git/memory Context Builder,
3. activity/event streaming,
4. VS Code Ask / Plan / Edit / Fix / Review / Agent modes,
5. diff review + verified repair apply controls,
6. post-apply regression monitoring + rollback API,
7. Improvement Agent and candidate prioritization only after the IDE/manual flow is proven.

---

# Implementation Progress — Part 3

The IDE layer from the roadmap is now partially implemented as a shared surface over the same safe backend contracts:

- persistent IDE sessions/events,
- `Ask`, `Plan`, `Edit`, `Fix`, `Review`, `Agent` orchestration,
- richer Context Agent,
- deterministic test discovery,
- targeted then broader regression validation,
- repair-loop activity events and SSE streaming,
- exact verified candidate diff/approval flow,
- post-apply verification + automatic snapshot rollback,
- repository tree/text/symbol navigation,
- VS Code 1.1.0 source using these APIs.

Verified baseline at the Part 3 boundary: **31 backend tests pass**, all `app.*` modules import, and the VS Code extension passes Node syntax validation.

The next implementation target is Phase 2/3 convergence: unified project health + Improvement Agent + manually-triggered improvement-cycle controller. Recurring autonomous scheduling remains intentionally disabled until those cycles are proven safe and measurable.

---

# Implementation Progress — Part 4

Part 4 implements the first manually-triggered organism controller while preserving the existing approval boundary.

Completed:

- deterministic unified project-health snapshot,
- persisted health snapshots,
- Improvement Agent registered in the shared runtime,
- evidence-backed candidate generation,
- risk/benefit/confidence/urgency/cost prioritization,
- manual + observe-only policies,
- persisted improvement-cycle state machine,
- append-only improvement events + SSE-compatible replay,
- repair attempts linked to improvement cycles,
- exact verified-repair reuse rather than a second code path,
- explicit approval before live writes,
- post-apply health monitoring,
- outcome memory,
- automatic rollback on material health-score regression,
- explicit rollback for already-applied verified repairs,
- backward-compatible SQLite migrations,
- **41 passing backend tests** and zero backend import failures.

The recurring scheduler remains disabled. The next implementation target is learning/experimentation: use prior outcomes to influence ranking, evaluate multiple isolated approaches, add stronger regression baselines and budgets, then only later evaluate guarded scheduling.

---

# Implementation Progress — Part 5

Part 5 strengthens the learning and experimentation layer while keeping recurring autonomy disabled.

Completed:

- deterministic strategy keys for improvement candidates,
- conservative strategy-performance statistics from measured outcomes,
- historical outcome retrieval during ranking,
- base priority + learned priority retained separately for auditability,
- optional `WAITING_SELECTION` state before repair,
- explicit user-selected candidate override,
- bounded multi-candidate experiment mode,
- independent candidate workspaces for every experiment,
- quality-based verified experiment winner selection,
- persisted `improvement_experiments`,
- cycle-level repair/attempt/file/patch-byte budgets,
- approved API-contract + architecture-layout baselines,
- deterministic drift detection,
- offline Python/Node dependency-health inspection,
- dependency + drift project-health dimensions,
- strategy-learning and experiment inspection APIs,
- backward-compatible SQLite migrations,
- **49 passing backend tests**, zero backend import failures, and clean VS Code extension validation.

Safety remains unchanged at the promotion boundary: no recurring scheduler, no experiment writes to the live project, and no verified candidate can be promoted without explicit `confirm=true` approval.

The next target is governance/observability rather than more autonomy: protect intentional API changes, remember test/coverage effects, detect semantic architecture drift, suppress repetitive candidates, allow experiment cancellation/discard, add project-specific policies, and expose the improvement system clearly in IDE/dashboard surfaces. A recurring scheduler remains the final step, not the next one.

---

# Implementation Progress — Part 6

Part 6 completes the governance/observability target that followed Part 5 while keeping recurring autonomy disabled.

Completed:

- versioned project-specific improvement policies with immutable human-approval requirement,
- per-cycle policy snapshots,
- exact verified-patch governance in isolated workspaces,
- protected approved API contracts and explicit protected routes,
- required/protected/forbidden architecture path invariants,
- optional top-level source-layout protection and changed-module size ceilings,
- dependency-manifest governance,
- second governance check immediately before live apply,
- verified-repair revocation for governance failures, discarded experiments and non-winning experiments,
- deterministic repeated-candidate fingerprints and suppression,
- historical test/check + coverage-signal impact memory,
- cooperative cycle cancellation,
- experiment discard controls,
- dashboard Improvements workspace,
- VS Code Improvement Center / Improve Project / Cancel Improvement commands,
- additive backward-compatible SQLite migration,
- **58 passing backend tests**, zero backend import failures, OpenAPI route validation, and clean VS Code extension validation.

The next target should be a guarded-autonomy **eligibility report**, not a scheduler: approval roles, immutable/signed policy evidence, real coverage delta ingestion, failure-class cooldowns, cross-cycle regression attribution and minimum manual-success-history requirements. Recurrence remains disabled until those checks are proven.


---

# Implementation Progress — Part 7

Part 7 implements the guarded-autonomy eligibility layer and still does not introduce recurrence.

Completed:

- canonical per-cycle policy snapshot integrity,
- optional HMAC-SHA256 signed policy snapshots,
- pre-apply integrity revalidation and `POLICY_INTEGRITY_BLOCKED`,
- local authenticated approver registry with tokens kept out of SQLite,
- minimum verified approval / required-role policy gates,
- coverage.py JSON and Cobertura coverage ingestion,
- baseline/post-apply coverage delta calculation,
- failure-class cooldown windows,
- historical candidate risk escalation,
- cross-cycle regression attribution,
- deterministic autonomy-readiness gates and `safe_to_automate` / `not_safe_to_automate` verdict,
- dashboard readiness + approval UI,
- VS Code Autonomy Readiness command and verified-approval prompts,
- additive backward-compatible SQLite migrations,
- **67 passing backend tests**.

The scheduler remains disabled, and a readiness pass does not enable source automation. The next stage should be a dry-run scheduler/control plane with maintenance windows, leases, rate limits, emergency stop, CI/SLO evidence and canary scheduling before any consideration of unattended promotion.

---

# Implementation Progress — Part 8

Part 8 introduces the first recurring control plane, deliberately limited to dry-run work.

Completed:

- persistent dry-run schedules,
- `observe_propose` schedules forced to `observe_only` improvement policy,
- `canary_observe` health-only schedules that never create repair cycles,
- timezone-aware maintenance windows,
- global and per-project concurrency leases with heartbeat/TTL,
- global/project/schedule rate limits,
- persistent emergency kill switch,
- CI/webhook evidence ingestion with optional shared-secret authentication and payload limits,
- SLO/error-budget evidence with freshness and threshold gates,
- Part 7 readiness gate integration,
- optional background polling disabled by default,
- scheduler history and lease inspection APIs,
- dashboard control-plane UI,
- VS Code extension 1.4.0 scheduler status/tick/emergency-stop commands,
- additive SQLite migrations,
- **78 passing backend tests**.

Automatic live source promotion remains disabled. The next stage should improve scheduler evidence integrity, auditability and distributed observability rather than removing the human promotion boundary.

---

# Implementation Progress — Part 9

Part 9 production-hardens the dry-run scheduler with signed/replay-protected external evidence, CI branch/commit binding, authenticated operator audit, environment policies, fenced leases, schedule simulation, persisted alerts and Prometheus-style metrics. The verified Part 9 boundary was **88 backend tests**.

Automatic source promotion remains disabled.

---

# Implementation Progress — Part 10

Part 10 focuses on deployment and operations rather than increasing autonomy.

Completed:

- durable external scheduler-alert outbox,
- optional signed HTTPS alert delivery,
- optional OTLP/HTTP scheduler telemetry export,
- pluggable fenced lease coordination (`sqlite`, optional Redis/PostgreSQL),
- background scheduler leader election,
- native GitHub/GitLab provenance adapters with replay protection,
- retention preview and confirmed compaction,
- non-destructive disaster-recovery backup drills with integrity and SHA-256 verification,
- operator/DR runbooks,
- dashboard Part 10 operational controls,
- VS Code extension 1.6.0 operations commands.

Part 10 still cannot promote scheduled changes into the live source tree. Any future Part 11 should focus on deployment packaging, external secret management and integration testing before reconsidering the existing human promotion boundary.


---

# Implementation Progress — Part 12

Part 12 adds a staging/release evidence layer without increasing live-source autonomy.

Completed:

- exact verified-repair release candidates,
- isolated TTL candidate workspaces,
- first-class validation + integration-test release checks,
- optional fixed-argument Docker candidate builds,
- CycloneDX 1.5 SBOM generation,
- HMAC-SHA256 signing of release artifacts/evidence,
- signed staging deployment manifests,
- Trivy/Grype/generic vulnerability evidence normalization and deterministic severity thresholds,
- expiring external preview records,
- signed aggregate release-evidence bundles,
- GitHub/GitLab staging-readiness status publication through the existing outbox,
- explicit operator-confirmed `staging_ready` promotion,
- release-workspace cleanup that retains evidence,
- dashboard Part 12 release controls,
- VS Code extension 1.8.0 Staging Release Center,
- additive SQLite migrations,
- **121 passing backend tests**.

Part 12 intentionally has no production deployment state and no production-promotion endpoint. The next phase should focus on CI/CD runner adapters, attestation standards such as Sigstore/SLSA, and external staging deployment providers before any production-release integration is considered.
