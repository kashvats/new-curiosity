from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Dict

from app.config import settings

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,511}$")


def _run(args: list[str], *, timeout: int | None = None) -> Dict[str, Any]:
    proc = subprocess.run(
        args, shell=False, capture_output=True, text=True,
        timeout=max(10, int(timeout or settings.PRODUCTION_DEPLOYER_COMMAND_TIMEOUT_SECONDS)),
    )
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "")[-12000:],
        "stderr": (proc.stderr or "")[-12000:],
        "args": args,
    }


def _required_text(target: Dict[str, Any], key: str) -> str:
    value = str(target.get(key) or "").strip()
    if not value or not _NAME.fullmatch(value):
        raise ValueError(f"Invalid or missing deployment target field: {key}")
    return value


def validate_target(provider: str, target: Dict[str, Any], binding: Dict[str, Any]) -> Dict[str, Any]:
    provider = str(provider or "").lower()
    allowed = {v.strip() for v in str(settings.PRODUCTION_DEPLOYER_ALLOWED_PROVIDERS).split(",") if v.strip()}
    if provider not in allowed:
        raise ValueError("Production deployment provider is not allowed")
    if str(target.get("environment") or "production").lower() != "production":
        raise ValueError("Independent production deployer only accepts environment=production")
    artifact_ref = str(target.get("artifact_ref") or "").strip()
    artifact_digest = str(target.get("artifact_digest") or "").lower().removeprefix("sha256:")
    if artifact_ref != str(binding.get("artifact_ref") or "") or artifact_digest != str(binding.get("digest_sha256") or "").lower().removeprefix("sha256:"):
        raise ValueError("Deployment target does not match the immutable artifact binding")
    if provider == "kubernetes":
        if binding.get("kind") != "oci_image":
            raise ValueError("Kubernetes production deployment requires an oci_image artifact binding")
        _required_text(target, "namespace"); _required_text(target, "deployment"); _required_text(target, "container")
        if target.get("context"): _required_text(target, "context")
    elif provider == "ecs":
        if binding.get("kind") != "ecs_task_definition":
            raise ValueError("ECS production deployment requires an ecs_task_definition artifact binding")
        _required_text(target, "cluster"); _required_text(target, "service")
    elif provider == "external":
        _required_text(target, "target_id")
    return dict(target)


def _kubectl_prefix(target: Dict[str, Any]) -> list[str]:
    prefix = ["kubectl"]
    if target.get("context"):
        prefix += ["--context", str(target["context"])]
    prefix += ["-n", str(target["namespace"])]
    return prefix


def execute_rolling(provider: str, target: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(settings.PRODUCTION_DEPLOYER_EXECUTION_ENABLED):
        raise RuntimeError("Production execution is disabled")
    if provider == "kubernetes":
        prefix = _kubectl_prefix(target)
        current = _run(prefix + ["get", "deployment", str(target["deployment"]), "-o", "json"])
        if not current["ok"]:
            raise RuntimeError(current["stderr"] or "Unable to inspect Kubernetes deployment")
        try:
            payload = json.loads(current["stdout"])
            containers = payload["spec"]["template"]["spec"]["containers"]
            previous_image = next(c["image"] for c in containers if c.get("name") == target["container"])
        except Exception as exc:
            raise RuntimeError("Unable to identify previous Kubernetes container image") from exc
        changed = _run(prefix + ["set", "image", f"deployment/{target['deployment']}", f"{target['container']}={target['artifact_ref']}"])
        if not changed["ok"]:
            raise RuntimeError(changed["stderr"] or "Kubernetes set image failed")
        waited = _run(prefix + ["rollout", "status", f"deployment/{target['deployment']}", f"--timeout={int(settings.PRODUCTION_DEPLOYER_COMMAND_TIMEOUT_SECONDS)}s"])
        if not waited["ok"]:
            raise RuntimeError(waited["stderr"] or "Kubernetes rollout did not become ready")
        return {"provider": provider, "previous_state": {"image": previous_image}, "result": waited}
    if provider == "ecs":
        desc = _run(["aws", "ecs", "describe-services", "--cluster", str(target["cluster"]), "--services", str(target["service"]), "--output", "json"])
        if not desc["ok"]:
            raise RuntimeError(desc["stderr"] or "Unable to inspect ECS service")
        try:
            previous = json.loads(desc["stdout"])["services"][0]["taskDefinition"]
        except Exception as exc:
            raise RuntimeError("Unable to identify previous ECS task definition") from exc
        updated = _run(["aws", "ecs", "update-service", "--cluster", str(target["cluster"]), "--service", str(target["service"]), "--task-definition", str(target["artifact_ref"]), "--output", "json"])
        if not updated["ok"]:
            raise RuntimeError(updated["stderr"] or "ECS update-service failed")
        waited = _run(["aws", "ecs", "wait", "services-stable", "--cluster", str(target["cluster"]), "--services", str(target["service"])])
        if not waited["ok"]:
            raise RuntimeError(waited["stderr"] or "ECS service did not become stable")
        return {"provider": provider, "previous_state": {"task_definition": previous}, "result": updated}
    raise RuntimeError("Direct rolling execution is not available for this provider")


def rollback(provider: str, target: Dict[str, Any], previous_state: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(settings.PRODUCTION_DEPLOYER_EXECUTION_ENABLED):
        return {"status": "rollback_requested", "executed": False, "reason": "production_execution_disabled"}
    if provider == "kubernetes" and previous_state.get("image"):
        prefix = _kubectl_prefix(target)
        result = _run(prefix + ["set", "image", f"deployment/{target['deployment']}", f"{target['container']}={previous_state['image']}"])
        if result["ok"]:
            _run(prefix + ["rollout", "status", f"deployment/{target['deployment']}", f"--timeout={int(settings.PRODUCTION_DEPLOYER_COMMAND_TIMEOUT_SECONDS)}s"])
        return {"status": "rolled_back" if result["ok"] else "rollback_failed", "executed": True, "result": result}
    if provider == "ecs" and previous_state.get("task_definition"):
        result = _run(["aws", "ecs", "update-service", "--cluster", str(target["cluster"]), "--service", str(target["service"]), "--task-definition", str(previous_state["task_definition"]), "--output", "json"])
        if result["ok"]:
            _run(["aws", "ecs", "wait", "services-stable", "--cluster", str(target["cluster"]), "--services", str(target["service"])])
        return {"status": "rolled_back" if result["ok"] else "rollback_failed", "executed": True, "result": result}
    return {"status": "rollback_requested", "executed": False, "reason": "external_or_missing_previous_state"}
