"""Machine-verifiable checks used by repair and IDE agent modes."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.safe_commands import run_safe_command


class VerificationService:
    def verify(self, project_root: str, validation_plan: Iterable[Dict[str, Any]] | None) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []
        for item in list(validation_plan or []):
            args = item.get("args") if isinstance(item, dict) else None
            if not isinstance(args, list):
                checks.append({"passed": False, "status": "invalid", "message": "Validation step missing args array"})
                continue
            try:
                result = run_safe_command(project_root, args, cwd=item.get("cwd"))
                row = result.to_dict()
                row["purpose"] = item.get("purpose", "")
                row["cwd"] = item.get("cwd")
                checks.append(row)
            except Exception as exc:
                checks.append({"passed": False, "status": "blocked", "args": args, "message": str(exc), "purpose": item.get("purpose", ""), "cwd": item.get("cwd")})

        if not checks:
            return {"passed": False, "status": "no_checks", "checks": [], "message": "No machine-verifiable validation plan was supplied"}
        passed = all(bool(c.get("passed")) for c in checks)
        return {"passed": passed, "status": "passed" if passed else "failed", "checks": checks}

    def verify_with_regression(
        self,
        project_root: str,
        targeted_plan: Iterable[Dict[str, Any]] | None,
        regression_plan: Iterable[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        targeted = self.verify(project_root, targeted_plan)
        result: Dict[str, Any] = {
            "passed": False,
            "status": targeted.get("status", "failed"),
            "checks": list(targeted.get("checks", [])),
            "targeted": targeted,
            "regression": {"passed": True, "status": "skipped", "checks": []},
        }
        if not targeted.get("passed"):
            return result

        targeted_args = {tuple(c.get("args") or []) for c in targeted.get("checks", [])}
        regression_items = [
            item for item in list(regression_plan or [])
            if tuple(item.get("args") or []) not in targeted_args
        ]
        if regression_items:
            regression = self.verify(project_root, regression_items)
            result["regression"] = regression
            result["checks"].extend(regression.get("checks", []))
            if not regression.get("passed"):
                result["status"] = "regression_failed"
                return result

        result["passed"] = True
        result["status"] = "passed"
        return result


verification_service = VerificationService()
