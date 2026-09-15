"""Part 13 provenance and attestation helpers for staging releases.

Produces an in-toto/SLSA-style provenance statement from already-recorded release
evidence. Optional Cosign execution is fixed-argument and disabled by default.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.config import settings
from app.improvement_release_security import sign_digest
from app.improvement_release_store import release_evidence
from app.improvement_staging_store import list_attestations, store_attestation


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_digest(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def build_slsa_provenance(release_id: str, *, builder_id: str = "ai-coding-assistant/part13") -> Dict[str, Any]:
    evidence = release_evidence(release_id)
    release = evidence["release"]
    subjects=[]
    for artifact in evidence.get("artifacts", []):
        digest=str(artifact.get("digest_sha256") or "")
        if digest:
            subjects.append({"name": str(artifact.get("name") or artifact.get("kind") or "artifact"), "digest": {"sha256": digest}})
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": sorted(subjects, key=lambda x: x["name"]),
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://openai.com/ai-coding-assistant/staging-candidate/v1",
                "externalParameters": {
                    "releaseId": release_id,
                    "project": release.get("project_name"),
                    "issueId": release.get("issue_id"),
                    "commitSha": release.get("commit_sha"),
                    "productionPromotionAllowed": False,
                },
                "internalParameters": {"orchestratorVersion": "13"},
                "resolvedDependencies": [],
            },
            "runDetails": {
                "builder": {"id": builder_id},
                "metadata": {"invocationId": release_id, "startedOn": release.get("created_at"), "finishedOn": _now()},
                "byproducts": [{"name": "release-check-count", "value": len(evidence.get("checks", []))}],
            },
        },
    }
    digest=canonical_digest(statement)
    signature=sign_digest(digest, context=f"release:{release_id}:slsa-provenance")
    return store_attestation(release_id=release_id, kind="slsa_provenance", predicate_type=statement["predicateType"],
                             digest_sha256=digest, statement=statement, signature=signature.get("signature"),
                             signature_algorithm=signature.get("algorithm"))


def build_release_attestation_summary(release_id: str) -> Dict[str, Any]:
    items=list_attestations(release_id)
    return {"release_id": release_id, "count": len(items), "items": items,
            "slsa_present": any(i.get("kind") == "slsa_provenance" for i in items),
            "production_promotion_allowed": False}


def cosign_attest(*, release_id: str, image_ref: str) -> Dict[str, Any]:
    """Optionally attach SLSA provenance to an OCI staging image using Cosign.

    Disabled by default. The command is fixed and shell=False; credential/key handling is
    delegated to the deployment environment's Cosign configuration.
    """
    if not bool(getattr(settings, "IMPROVEMENT_RELEASE_COSIGN_ENABLED", False)):
        return {"status": "skipped", "reason": "cosign_disabled", "image_ref": image_ref}
    if not image_ref or any(ch.isspace() for ch in image_ref) or "@" not in image_ref and ":" not in image_ref:
        raise ValueError("A concrete OCI image reference is required for Cosign attestation")
    attestations=[a for a in list_attestations(release_id) if a.get("kind") == "slsa_provenance"]
    if not attestations:
        raise ValueError("SLSA provenance must be generated before Cosign attestation")
    statement=attestations[-1]["statement"]
    with tempfile.TemporaryDirectory(prefix="aca-cosign-") as tmp:
        predicate=Path(tmp)/"provenance.json"
        predicate.write_text(json.dumps(statement["predicate"], ensure_ascii=False, sort_keys=True), encoding="utf-8")
        args=["cosign","attest","--yes","--type","slsaprovenance","--predicate",str(predicate),image_ref]
        proc=subprocess.run(args, shell=False, capture_output=True, text=True,
                            timeout=max(30,int(getattr(settings,"IMPROVEMENT_RELEASE_BUILD_TIMEOUT_SECONDS",900))))
    result={"status":"passed" if proc.returncode==0 else "failed", "exit_code":proc.returncode,
            "image_ref":image_ref, "stdout":(proc.stdout or "")[-4000:], "stderr":(proc.stderr or "")[-4000:]}
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "cosign attest failed")[-2000:])
    return result
