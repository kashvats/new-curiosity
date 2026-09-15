# v1.1 Intelligence, Performance & Learning Improvement Report

## Goal

v1.1 improves the existing Part 16 architecture instead of adding another autonomous subsystem. The focus is coding quality per model call, repository context quality, contextual learning from mistakes, and measurable evaluation.

## Changes

### Adaptive agent routing

`app/adaptive_orchestration.py` classifies a request deterministically by task kind, complexity, explicit evidence, file scope, security sensitivity and architecture impact.

For a bounded feature/edit, the first repair attempt no longer performs an unconditional Debugger LLM call. The path becomes:

```text
context -> coder -> machine validation -> reviewer -> security -> quality
```

If validation fails, attempt two automatically escalates to:

```text
debugger -> coder -> machine validation -> reviewer -> security -> quality
```

Debug/security tasks still use the debugger immediately. Cross-cutting/high-complexity orchestration still uses the planner. Verified-candidate gates were not removed or weakened.

### Planner-call reduction

The high-level orchestrator now creates a deterministic single-phase plan for simple bounded work. It calls the Planner model only when routing identifies architecture/cross-cutting/high-complexity work.

### Repository intelligence

`app/repository_intelligence.py` builds a bounded local code graph without an LLM or embedding request. It extracts:

- source files,
- symbols,
- local imports,
- reverse import relationships,
- simple call names,
- source/test counterparts.

Relevant files are ranked using task terms, symbols, explicit seed files and graph neighbors. The selected graph context is used by the IDE Context Agent and Coder.

### Contextual engineering experience memory

`app/experience_memory.py` persists project-scoped engineering experiences with:

- problem/task terms,
- strategy,
- outcome,
- failure class,
- affected files,
- validation status,
- lesson,
- occurrence count.

Retrieval is contextual. A failed authentication strategy does not globally poison the same strategy for unrelated UI work. Similar prior failures and successes are injected into future repair context. Production strategy history from Part 15 is also included when it matches the current strategy.

This remains operational memory, not model-weight training.

### Model usage telemetry

`app/model_usage.py` records only metadata:

- provider,
- model,
- operation,
- duration,
- prompt/output character counts,
- comparable char/4 token estimates,
- success/failure type.

Prompt and completion text are intentionally not persisted in this telemetry table.

### Evaluation framework

`app/v11_evaluation.py` adds two layers:

1. historical repair-efficiency summaries;
2. explicit benchmark-run storage for version comparisons.

Benchmark cases can capture:

- task success,
- regression status,
- LLM call count,
- token count,
- duration,
- changed-file count.

This provides a stable basis for comparing v1.0, v1.1 and later releases.

## New API

Prefix: `/v1.1`

- `GET /v1.1/capabilities`
- `POST /v1.1/routing/preview`
- `POST /v1.1/repository/context`
- `POST /v1.1/experiences/search`
- `GET /v1.1/evaluation/repair-efficiency`
- `GET /v1.1/evaluation/model-usage`
- `POST /v1.1/evaluation/benchmarks`
- `GET /v1.1/evaluation/benchmarks`

## Persistence

New additive SQLite tables:

- `engineering_experiences`
- `v11_benchmark_runs`
- `v11_model_usage`

## Safety invariants

v1.1 does not alter the Part 16 trust model:

- candidate work remains isolated;
- machine verification remains required;
- reviewer/security/quality gates remain required for verified repairs;
- human approval/governance boundaries remain intact;
- the AI backend still has zero production execution routes;
- the independent production deployer remains a separate trust boundary.

## Expected efficiency improvement

For a simple bounded repair that succeeds on the first attempt, v1.0 always paid for an initial Debugger call. v1.1 avoids it. For simple high-level orchestrator work, v1.1 can also avoid a Planner call. Exact savings depend on task mix and are now measurable through `/v1.1/evaluation/model-usage` and benchmark runs.

### Repository graph hot-path caching

The deterministic repository graph keeps a short bounded in-process cache (`V11_REPOSITORY_GRAPH_CACHE_SECONDS`, default 3s). This avoids reparsing the same repository repeatedly inside one interactive operation while keeping the staleness window deliberately small.

### Benchmark comparison

`GET /v1.1/evaluation/compare` compares the latest stored benchmark runs for a baseline and candidate release and reports deltas for success rate, regression rate, LLM calls, estimated tokens, duration, and files changed.

### VS Code

Extension v1.13.0 adds **AI Coding Assistant: Intelligence & Efficiency**, exposing v1.1 routing and efficiency telemetry without exposing prompt content.


## Final validation

- Backend regression tests: **169 passed** (88 + 81 clean batches)
- Independent production deployer: **12 passed**
- v1.1-specific tests: **12 passed**
- Backend modules: **133**, import failures: **0**
- FastAPI paths: **196**
- v1.1 paths: **8**
- Deterministic security findings in changed control/intelligence code: **0 critical / 0 high / 0 medium / 0 low**
- VS Code extension syntax/manifest: **PASS**
- VS Code extension version: **1.13.0**
- Frontend package manifest: **PASS**
- Docker Compose YAML: **PASS**

The frontend archive intentionally contains no `node_modules`, so a Vite production build is not claimed in this validation environment.
