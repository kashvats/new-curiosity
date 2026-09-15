from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.config import settings


def canonical_digest(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _secret(name: str) -> str:
    value = str(getattr(settings, name, "") or os.environ.get(name, "") or "")
    if value:
        return value
    root = Path(str(settings.PRODUCTION_DEPLOYER_SECRETS_DIR))
    path = root / name
    try:
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    except Exception:
        return ""


def _candidate_keys(key_name: str) -> list[str]:
    keys: list[str] = []
    current = _secret(key_name)
    if current:
        keys.append(current)
    previous_name = {
        "PRODUCTION_DEPLOYER_PACKAGE_SIGNING_KEY": "PRODUCTION_DEPLOYER_PREVIOUS_PACKAGE_SIGNING_KEYS",
        "PRODUCTION_DEPLOYER_RECEIPT_SIGNING_KEY": "PRODUCTION_DEPLOYER_PREVIOUS_RECEIPT_SIGNING_KEYS",
    }.get(key_name)
    if previous_name:
        raw = _secret(previous_name) or str(getattr(settings, previous_name, "") or "")
        for item in raw.split(","):
            item = item.strip()
            if item and item not in keys:
                keys.append(item)
    return keys


def verify_hmac(digest_sha256: str, *, context: str, signature: str | None, key_name: str = "PRODUCTION_DEPLOYER_PACKAGE_SIGNING_KEY") -> bool:
    if not signature:
        return False
    message = f"{context}:{digest_sha256}".encode("utf-8")
    for key in _candidate_keys(key_name):
        expected = hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, str(signature)):
            return True
    return False


def sign_receipt(digest_sha256: str) -> Dict[str, Any]:
    key = _secret("PRODUCTION_DEPLOYER_RECEIPT_SIGNING_KEY")
    if not key:
        return {"signed": False, "signature": None, "algorithm": None}
    signature = hmac.new(key.encode("utf-8"), f"production-deployment-receipt:{digest_sha256}".encode("utf-8"), hashlib.sha256).hexdigest()
    return {"signed": True, "signature": signature, "algorithm": "hmac-sha256"}


def verify_operator(operator_id: str | None, token: str | None) -> Dict[str, Any]:
    try:
        registry = json.loads(str(settings.PRODUCTION_DEPLOYER_OPERATOR_CREDENTIALS_JSON or "{}"))
    except Exception:
        registry = {}
    if not registry:
        raise ValueError("Production deployer operator registry is not configured")
    item = registry.get(str(operator_id or "")) if isinstance(registry, dict) else None
    if not isinstance(item, dict) or not token:
        raise ValueError("Production deployer operator credentials are required")
    expected = str(item.get("token") or "")
    if not expected or not hmac.compare_digest(expected, str(token)):
        raise ValueError("Production deployer operator credentials are invalid")
    role = str(item.get("role") or "")
    allowed = {x.strip() for x in str(settings.PRODUCTION_DEPLOYER_ALLOWED_OPERATOR_ROLES).split(",") if x.strip()}
    if role not in allowed:
        raise ValueError("Operator role is not authorized for production deployment")
    return {"verified": True, "operator_id": str(operator_id), "role": role}


def _parse_at(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def verify_package_and_authorization(package: Dict[str, Any], authorization: Dict[str, Any]) -> Dict[str, Any]:
    errors: list[str] = []
    payload = package.get("payload") if isinstance(package.get("payload"), dict) else {}
    computed = canonical_digest(payload)
    digest = str(package.get("digest_sha256") or "")
    case_id = str(package.get("case_id") or payload.get("case_id") or "")
    package_sig_ok = computed == digest and verify_hmac(digest, context=f"production-governance:{case_id}:deployment-package", signature=package.get("signature"))
    if not package_sig_ok:
        errors.append("deployment_package_signature_invalid")
    if str(payload.get("audience") or "") != str(settings.PRODUCTION_DEPLOYER_EXPECTED_AUDIENCE):
        errors.append("deployment_package_audience_mismatch")
    safety = payload.get("safety") or {}
    if safety.get("production_credentials_included") is not False or safety.get("backend_can_execute_production") is not False:
        errors.append("deployment_package_safety_contract_invalid")
    lock = payload.get("governance_lock") or {}
    lock_digest = str(lock.get("digest") or "")
    if not verify_hmac(lock_digest, context=f"production-governance:{case_id}:lock", signature=lock.get("signature")):
        errors.append("governance_lock_signature_invalid")
    approvals = payload.get("approvals") if isinstance(payload.get("approvals"), list) else []
    distinct = {str(a.get("approver_id") or "") for a in approvals if a.get("decision") == "approve" and a.get("approver_id")}
    roles = {str(a.get("role") or "") for a in approvals if a.get("decision") == "approve"}
    if len(distinct) < max(1, int(settings.PRODUCTION_DEPLOYER_MIN_APPROVALS)):
        errors.append("approval_quorum_not_met")
    required_roles = {x.strip() for x in str(settings.PRODUCTION_DEPLOYER_REQUIRED_APPROVAL_ROLES).split(",") if x.strip()}
    if not required_roles.issubset(roles):
        errors.append("required_approval_roles_missing")
    binding = payload.get("artifact_binding") or {}
    if not binding.get("artifact_ref") or not binding.get("digest_sha256") or binding.get("immutable") is not True:
        errors.append("immutable_artifact_binding_missing")

    auth_payload = authorization.get("payload") if isinstance(authorization.get("payload"), dict) else {}
    auth_digest = str(authorization.get("digest_sha256") or "")
    auth_id = str(authorization.get("id") or auth_payload.get("authorization_id") or "")
    auth_computed = canonical_digest(auth_payload)
    auth_sig_ok = auth_computed == auth_digest and verify_hmac(auth_digest, context=f"production-deployment-authorization:{auth_id}", signature=authorization.get("signature"))
    if not auth_sig_ok:
        errors.append("deployment_authorization_signature_invalid")
    if str(auth_payload.get("package_id") or "") != str(package.get("id") or "") or str(auth_payload.get("package_digest") or "") != digest:
        errors.append("deployment_authorization_package_mismatch")
    if auth_payload.get("single_use") is not True:
        errors.append("deployment_authorization_not_single_use")
    expires = _parse_at(auth_payload.get("expires_at") or authorization.get("expires_at"))
    if not expires or expires <= datetime.now(timezone.utc):
        errors.append("deployment_authorization_expired")
    if canonical_digest(auth_payload.get("artifact_binding") or {}) != canonical_digest(binding):
        errors.append("deployment_authorization_artifact_mismatch")
    return {"valid": not errors, "errors": errors, "package_digest": digest, "artifact_binding": binding, "authorization_id": auth_id}


_SENSITIVE_TOKENS = {"password", "secret", "token", "credential", "kubeconfig", "access_key", "secret_key", "private_key"}


def reject_embedded_credentials(value: Any, *, path: str = "target") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lower = str(key).lower()
            if any(token in lower for token in _SENSITIVE_TOKENS):
                raise ValueError(f"Production credentials must not be supplied in API payloads ({path}.{key})")
            reject_embedded_credentials(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            reject_embedded_credentials(child, path=f"{path}[{idx}]")
