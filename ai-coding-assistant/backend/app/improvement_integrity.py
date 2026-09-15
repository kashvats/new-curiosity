"""Policy snapshot integrity for governed improvement cycles.

Part 7 never enables autonomous scheduling. This module makes a cycle's resolved
policy tamper-evident between creation, validation and apply. If a signing key is
configured the snapshot is HMAC-SHA256 signed; otherwise a plain SHA-256 digest is
still persisted for deterministic corruption/tamper detection, but readiness will
not treat unsigned policy evidence as sufficient for guarded automation.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict

from app.config import settings


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def policy_snapshot_digest(snapshot: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(snapshot or {}).encode("utf-8")).hexdigest()


def seal_policy_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    digest = policy_snapshot_digest(snapshot)
    key = str(getattr(settings, "IMPROVEMENT_POLICY_SIGNING_KEY", "") or "")
    signature = hmac.new(key.encode("utf-8"), digest.encode("ascii"), hashlib.sha256).hexdigest() if key else None
    return {
        "algorithm": "hmac-sha256" if key else "sha256",
        "digest": digest,
        "signature": signature,
        "signed": bool(key),
    }


def verify_policy_snapshot(snapshot: Dict[str, Any], integrity: Dict[str, Any] | None) -> Dict[str, Any]:
    integrity = dict(integrity or {})
    actual = policy_snapshot_digest(snapshot)
    expected = str(integrity.get("digest") or "")
    digest_ok = bool(expected) and hmac.compare_digest(expected, actual)
    signed = bool(integrity.get("signed")) or str(integrity.get("algorithm") or "").lower() == "hmac-sha256"
    signature_ok = None
    reason = None
    if not digest_ok:
        reason = "policy_snapshot_digest_mismatch" if expected else "policy_snapshot_integrity_missing"
    if signed:
        key = str(getattr(settings, "IMPROVEMENT_POLICY_SIGNING_KEY", "") or "")
        supplied = str(integrity.get("signature") or "")
        if not key:
            signature_ok = False
            reason = reason or "policy_signing_key_unavailable"
        else:
            expected_sig = hmac.new(key.encode("utf-8"), actual.encode("ascii"), hashlib.sha256).hexdigest()
            signature_ok = bool(supplied) and hmac.compare_digest(supplied, expected_sig)
            if not signature_ok:
                reason = reason or "policy_snapshot_signature_mismatch"
    passed = digest_ok and (signature_ok is not False)
    return {
        "passed": passed,
        "digest_ok": digest_ok,
        "signature_ok": signature_ok,
        "signed": signed,
        "algorithm": integrity.get("algorithm") or ("hmac-sha256" if signed else "sha256"),
        "digest": actual,
        "reason": reason,
    }
