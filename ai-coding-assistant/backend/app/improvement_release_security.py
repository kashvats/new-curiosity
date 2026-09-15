"""Part 12 release evidence: SBOMs, signatures and vulnerability gates."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.config import settings
from app.improvement_secrets import get_secret

_REQ_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*(?:===|==|>=|<=|~=|!=|>|<)?\s*([^;\s]+)?")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_signing_status() -> Dict[str, Any]:
    configured = bool(get_secret("IMPROVEMENT_RELEASE_SIGNING_KEY"))
    return {
        "configured": configured,
        "algorithm": "hmac-sha256" if configured else None,
        "required": bool(getattr(settings, "IMPROVEMENT_RELEASE_REQUIRE_SIGNATURE", True)),
        "key_exposed": False,
        "production_promotion_allowed": False,
    }


def sign_digest(digest_sha256: str, *, context: str) -> Dict[str, Any]:
    key = get_secret("IMPROVEMENT_RELEASE_SIGNING_KEY")
    if not key:
        return {"signed": False, "signature": None, "algorithm": None, "reason": "signing_key_not_configured"}
    message = f"{context}:{digest_sha256}".encode("utf-8")
    signature = hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {"signed": True, "signature": signature, "algorithm": "hmac-sha256"}


def verify_digest_signature(digest_sha256: str, *, context: str, signature: str | None) -> bool:
    expected = sign_digest(digest_sha256, context=context)
    return bool(expected.get("signed") and signature and hmac.compare_digest(str(expected["signature"]), str(signature)))


def _python_components(root: Path) -> List[Dict[str, Any]]:
    components: list[Dict[str, Any]] = []
    for filename in ("requirements.txt", "requirements-operations.txt"):
        path = root / filename
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip().replace("\x00", "")
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            match = _REQ_RE.match(line)
            if not match:
                continue
            name = match.group(1); version = (match.group(2) or "").strip()
            component = {"type": "library", "name": name, "purl": f"pkg:pypi/{name.lower()}"}
            if version and version not in {"*"}:
                component["version"] = version
                component["purl"] += f"@{version}"
            components.append(component)
    return components


def _node_components(root: Path) -> List[Dict[str, Any]]:
    components: list[Dict[str, Any]] = []
    for package_path in root.rglob("package.json"):
        if any(part in {"node_modules", ".git", "dist", "build"} for part in package_path.parts):
            continue
        try:
            payload = json.loads(package_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            deps = payload.get(section) or {}
            if not isinstance(deps, dict):
                continue
            for name, version in deps.items():
                version = str(version)
                clean_version = version.lstrip("^~=> <")
                component = {"type": "library", "name": str(name), "version": version,
                             "purl": f"pkg:npm/{str(name).replace('@','%40')}@{clean_version}", "scope": section}
                components.append(component)
    return components


def generate_sbom(project_root: str | Path, *, serial: str) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    components = _python_components(root) + _node_components(root)
    # Deterministic ordering + de-duplication keeps hashes stable for the same candidate.
    unique: dict[tuple[str, str, str], Dict[str, Any]] = {}
    for component in components:
        key = (str(component.get("type")), str(component.get("name")), str(component.get("version", "")))
        unique[key] = component
    normalized = sorted(unique.values(), key=lambda c: (str(c.get("type")), str(c.get("name")).lower(), str(c.get("version", ""))))
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{serial}", "version": 1,
        "metadata": {"timestamp": _now(), "tools": [{"vendor": "OpenAI", "name": "AI Coding Assistant release orchestrator", "version": "12"}]},
        "components": normalized,
    }


def normalize_vulnerability_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0}
    findings: list[Dict[str, Any]] = []

    def add(severity: Any, finding: Dict[str, Any]) -> None:
        sev = str(severity or "unknown").strip().lower()
        if sev not in counts: sev = "unknown"
        counts[sev] += 1
        if len(findings) < 500:
            findings.append({"severity": sev, **{k: v for k, v in finding.items() if k in {"id", "package", "version", "fixed_version", "title", "target"}}})

    # Trivy JSON
    for result in payload.get("Results", []) if isinstance(payload.get("Results"), list) else []:
        target = result.get("Target")
        for vuln in result.get("Vulnerabilities") or []:
            add(vuln.get("Severity"), {"id": vuln.get("VulnerabilityID"), "package": vuln.get("PkgName"),
                 "version": vuln.get("InstalledVersion"), "fixed_version": vuln.get("FixedVersion"), "title": vuln.get("Title"), "target": target})
    # Grype JSON
    for match in payload.get("matches", []) if isinstance(payload.get("matches"), list) else []:
        vuln = match.get("vulnerability") or {}; artifact = match.get("artifact") or {}
        add(vuln.get("severity"), {"id": vuln.get("id"), "package": artifact.get("name"), "version": artifact.get("version"),
                                   "fixed_version": ",".join(vuln.get("fix", {}).get("versions", []) or []), "title": vuln.get("description")})
    # Generic normalized format.
    generic = payload.get("findings")
    if isinstance(generic, list):
        for item in generic:
            if isinstance(item, dict): add(item.get("severity"), item)
    if not findings and isinstance(payload.get("counts"), dict):
        for key in counts:
            try: counts[key] = max(0, int(payload["counts"].get(key, 0)))
            except Exception: pass

    policy = {
        "critical": int(getattr(settings, "IMPROVEMENT_RELEASE_MAX_CRITICAL_VULNS", 0)),
        "high": int(getattr(settings, "IMPROVEMENT_RELEASE_MAX_HIGH_VULNS", 0)),
        "medium": int(getattr(settings, "IMPROVEMENT_RELEASE_MAX_MEDIUM_VULNS", 20)),
    }
    violations = [f"{sev}={counts[sev]} exceeds max={limit}" for sev, limit in policy.items() if counts[sev] > limit]
    return {"counts": counts, "findings": findings, "policy": policy, "passed": not violations, "violations": violations}


def run_trivy_filesystem_scan(project_root: str | Path) -> Dict[str, Any]:
    """Run a fixed-argument Trivy filesystem scan when explicitly configured.

    No shell is used. The scanner is optional because vulnerability DB lifecycle is an
    infrastructure responsibility; report_only is the safer default for offline installs.
    """
    if str(getattr(settings, "IMPROVEMENT_RELEASE_VULN_SCANNER", "report_only")).lower() != "trivy":
        raise RuntimeError("Trivy scanning is not enabled")
    root = Path(project_root).resolve()
    proc = subprocess.run(
        ["trivy", "fs", "--format", "json", "--scanners", "vuln", "--quiet", str(root)],
        shell=False, capture_output=True, text=True, timeout=max(30, int(getattr(settings, "IMPROVEMENT_RELEASE_BUILD_TIMEOUT_SECONDS", 900))),
    )
    if proc.returncode not in {0, 1}:
        raise RuntimeError((proc.stderr or "trivy failed")[-2000:])
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Trivy returned invalid JSON") from exc
    return normalize_vulnerability_report(payload)
