# v1.1 Intelligence & Efficiency Runbook

## Purpose

v1.1 improves coding intelligence and efficiency without increasing deployment autonomy.

## Inspect routing before running a task

```http
POST /v1.1/routing/preview
```

```json
{
  "task": "Fix authentication timeout regression",
  "files": ["app/auth.py"],
  "evidence": {"terminal_output": "TimeoutError"}
}
```

A debug/security task should show `needs_initial_debugger=true`. A small feature should normally show it as false.

## Inspect repository context

```http
POST /v1.1/repository/context
```

The result explains why each file was selected and shows graph neighbors. If irrelevant files dominate, adjust file seeds or reduce `V11_REPOSITORY_CONTEXT_MAX_FILES`.

## Inspect experience memory

```http
POST /v1.1/experiences/search
```

Experience memory is project-scoped and contextual. It stores engineering outcomes, not hidden model weights.

## Measure model usage

```http
GET /v1.1/evaluation/model-usage
```

The usage table contains metadata only. It never stores prompt/completion text.

## Compare releases with benchmark runs

Record the same task suite for each release:

```http
POST /v1.1/evaluation/benchmarks
```

Recommended metrics per case:

- `passed`
- `regression`
- `llm_calls`
- `tokens`
- `duration_ms`
- `files_changed`

Do not claim v1.2 is better than v1.1 unless the same benchmark suite supports the claim.

## Disable individual v1.1 optimizations

All new intelligence features are independently configurable:

```env
V11_ADAPTIVE_ROUTING_ENABLED=false
V11_REPOSITORY_CONTEXT_ENABLED=false
V11_EXPERIENCE_MEMORY_ENABLED=false
V11_MODEL_USAGE_TELEMETRY_ENABLED=false
```

Disabling them falls back toward the existing Part 16 behavior without changing release/deployment governance.


## Compare two releases

```http
GET /v1.1/evaluation/compare?suite_name=<suite>&baseline_version=1.0.0&candidate_version=1.1.0
```

A claim that a newer release is better should be backed by the same task suite and these deltas, not by different ad-hoc examples.
