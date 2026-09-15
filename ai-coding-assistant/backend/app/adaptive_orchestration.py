"""Deterministic task routing for v1.1.

The goal is not to replace specialist agents with another model call.  It chooses the
smallest safe agent path from task/evidence characteristics so trivial work does not
pay for every specialist while failures still escalate to debugger/reviewer/security.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Dict, Iterable, List


_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]{2,}")

_DEBUG_TERMS = {
    "error", "exception", "traceback", "crash", "failing", "failure", "failed",
    "regression", "incorrect", "broken", "timeout", "deadlock", "hang", "bug",
    "debug", "root", "cause", "stacktrace", "segfault",
}
_SECURITY_TERMS = {
    "security", "vulnerability", "unsafe", "injection", "xss", "csrf", "auth",
    "authorization", "permission", "credential", "secret", "token", "shell",
    "sql", "path traversal", "ssrf", "rce",
}
_ARCH_TERMS = {
    "architecture", "migration", "schema", "distributed", "database", "refactor",
    "multi-file", "service", "queue", "cache", "protocol", "contract", "breaking",
}
_DOC_TERMS = {"readme", "documentation", "docs", "comment", "typo", "copy", "text"}
_TEST_TERMS = {"test", "pytest", "spec", "coverage", "regression"}
_FEATURE_TERMS = {"add", "implement", "feature", "create", "support", "introduce", "build"}


def _terms(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RE.finditer(text or "")}


def _contains_phrase(text: str, phrases: Iterable[str]) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in phrases)


@dataclass(frozen=True)
class TaskRoute:
    task_kind: str
    complexity: str
    needs_initial_debugger: bool
    needs_planner: bool
    expand_repository_context: bool
    context_file_budget: int
    default_strategy: str
    agent_sequence: List[str]
    estimated_llm_calls_before_validation: int
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def route_task(
    task: str,
    *,
    files: Iterable[str] = (),
    evidence: Dict[str, Any] | None = None,
) -> TaskRoute:
    """Return a deterministic, auditable route for a coding task.

    Reviewer/security gates remain part of verified repair.  The optimization is
    mainly avoiding an unnecessary *initial* debugger/planner LLM call and choosing
    an appropriate context budget.
    """
    evidence = evidence or {}
    files = [str(x) for x in files if str(x)]
    text = task or ""
    terms = _terms(text)
    reasons: list[str] = []

    has_failure_evidence = bool(
        evidence.get("diagnostics")
        or evidence.get("terminal_output")
        or evidence.get("traceback")
        or evidence.get("error")
        or evidence.get("failed_check")
    )
    security = bool(terms & _SECURITY_TERMS) or _contains_phrase(text, ("path traversal", "command injection", "sql injection"))
    debug = bool(terms & _DEBUG_TERMS) or has_failure_evidence
    architecture = bool(terms & _ARCH_TERMS)
    docs = bool(terms & _DOC_TERMS) and not (debug or security or architecture)
    tests = bool(terms & _TEST_TERMS)
    feature = bool(terms & _FEATURE_TERMS)

    if security:
        kind = "security"
        reasons.append("security-sensitive terms detected")
    elif debug:
        kind = "debug"
        reasons.append("failure/debug evidence detected")
    elif docs:
        kind = "documentation"
        reasons.append("documentation-only intent detected")
    elif architecture:
        kind = "architecture"
        reasons.append("cross-cutting/architecture terms detected")
    elif tests:
        kind = "tests"
        reasons.append("test-focused task detected")
    elif feature:
        kind = "feature"
        reasons.append("feature implementation intent detected")
    else:
        kind = "targeted_change"
        reasons.append("no high-risk or failure signal detected")

    task_length = len(text)
    if architecture or len(files) >= 5 or task_length > 1200:
        complexity = "high"
    elif security or debug or len(files) >= 2 or task_length > 350:
        complexity = "medium"
    else:
        complexity = "low"

    explicit_security_failure = security and bool(terms & {
        "vulnerability", "unsafe", "injection", "xss", "csrf", "rce", "ssrf", "exploit"
    })
    needs_initial_debugger = debug or explicit_security_failure
    # Planner is valuable for cross-cutting work. Security-sensitive feature work may
    # need a plan, but merely mentioning auth/token should not force a debugger call.
    needs_planner = architecture or complexity == "high" or (security and feature and len(files) >= 2)
    expand_repository_context = len(files) < 4 or architecture or debug
    context_budget = {"low": 6, "medium": 8, "high": 12}[complexity]

    sequence: list[str] = ["context"]
    if needs_planner:
        sequence.append("planner")
    if needs_initial_debugger:
        sequence.append("debugger")
    sequence.extend(["coder", "tester", "reviewer", "security"])

    # Before validation, coder is one LLM call; debugger/planner add one each.
    pre_validation_calls = 1 + int(needs_initial_debugger) + int(needs_planner)
    if not needs_initial_debugger:
        reasons.append("initial debugger call avoided; retries still escalate to debugger")
    if not needs_planner:
        reasons.append("planner call avoided for bounded task")

    strategy = {
        "debug": "diagnose_then_targeted_fix",
        "security": "security_preserving_targeted_fix",
        "architecture": "incremental_architecture_change",
        "documentation": "minimal_documentation_change",
        "tests": "test_focused_change",
        "feature": "minimal_feature_slice",
    }.get(kind, "direct_targeted_change")

    return TaskRoute(
        task_kind=kind,
        complexity=complexity,
        needs_initial_debugger=needs_initial_debugger,
        needs_planner=needs_planner,
        expand_repository_context=expand_repository_context,
        context_file_budget=context_budget,
        default_strategy=strategy,
        agent_sequence=sequence,
        estimated_llm_calls_before_validation=pre_validation_calls,
        reasons=reasons,
    )


def deterministic_single_phase_plan(task: str, route: TaskRoute) -> Dict[str, Any]:
    """Create a small no-LLM plan for tasks that do not need architectural planning."""
    return {
        "goal": task.strip()[:500] or "Complete requested change",
        "summary": f"Adaptive {route.task_kind} route with machine verification.",
        "recommended_stack": [],
        "phases": [{
            "id": 1,
            "title": "Implement and verify targeted change",
            "description": task.strip(),
            "files_likely_needed": [],
        }],
        "risks": [],
        "next_phase_prompt": "Implement the verified targeted change",
        "adaptive_route": route.to_dict(),
        "planner_skipped": True,
    }
