"""Deterministic security gate for proposed source changes.

This is intentionally scanner-independent so every repair can receive a fast gate.
Full Bandit/Semgrep scans remain available for deeper audits.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


_RULES = [
    ("critical", "shell_true", re.compile(r"subprocess\.(?:run|Popen|call|check_output|check_call)\s*\([^\n]*shell\s*=\s*True", re.I), "Shell execution with shell=True"),
    ("high", "dynamic_eval", re.compile(r"\b(?:eval|exec)\s*\("), "Dynamic eval/exec introduced"),
    ("high", "pickle_load", re.compile(r"\bpickle\.loads?\s*\("), "Unsafe pickle deserialization introduced"),
    ("high", "yaml_unsafe_load", re.compile(r"\byaml\.load\s*\([^\n]*Loader\s*=\s*yaml\.(?:Loader|UnsafeLoader)", re.I), "Unsafe YAML loader introduced"),
    ("high", "hardcoded_secret", re.compile(r"(?i)(?:api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"\n]{8,}['\"]"), "Possible hard-coded credential introduced"),
    ("medium", "sql_interpolation", re.compile(r"(?is)(?:execute|executemany)\s*\(\s*f['\"].*(?:select|insert|update|delete)"), "Possible SQL interpolation introduced"),
    ("medium", "ssl_verify_disabled", re.compile(r"verify\s*=\s*False"), "TLS verification disabled"),
]


def review_security(changes: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    for change in changes:
        path = str(change.get("path", ""))
        content = str(change.get("content", ""))
        for severity, rule_id, pattern, message in _RULES:
            if pattern.search(content):
                findings.append({"severity": severity, "rule_id": rule_id, "path": path, "message": message})

    counts = {level: sum(1 for f in findings if f["severity"] == level) for level in ("critical", "high", "medium", "low")}
    approved = counts["critical"] == 0 and counts["high"] == 0
    return {
        "approved": approved,
        "risk": "critical" if counts["critical"] else ("high" if counts["high"] else ("medium" if counts["medium"] else "low")),
        "findings": findings,
        "counts": counts,
    }
