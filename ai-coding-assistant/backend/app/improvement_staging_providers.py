"""Part 13 staging CI/deployment/OCI provider adapters.

All external execution is staging-scoped and disabled by default. No function in this
module can deploy to an environment named production/prod.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

import httpx

from app.config import settings
from app.improvement_secrets import get_secret

_SAFE_NAME=re.compile(r"^[A-Za-z0-9._:/@+-]+$")


def _reject_production(value: str, *, label: str) -> None:
    lowered=str(value or "").lower()
    tokens={v.strip().lower() for v in str(getattr(settings,"IMPROVEMENT_STAGING_PRODUCTION_DENY_TOKENS","prod,production")).split(",") if v.strip()}
    parts={p for p in re.split(r"[^a-z0-9]+", lowered) if p}
    if tokens & parts:
        raise ValueError(f"{label} must be staging-scoped; production-like target rejected")


def _safe_name(value: str, *, label: str) -> str:
    value=str(value or "").strip()
    if not value or len(value)>300 or not _SAFE_NAME.fullmatch(value):
        raise ValueError(f"Invalid {label}")
    _reject_production(value,label=label)
    return value


def provider_capabilities() -> Dict[str, Any]:
    return {
        "ci_providers":["github_actions","gitlab_pipeline"],
        "deployment_providers":["external","kubernetes","ecs"],
        "oci_promotion":True,
        "execution_enabled":bool(getattr(settings,"IMPROVEMENT_STAGING_EXECUTION_ENABLED",False)),
        "oci_execution_enabled":bool(getattr(settings,"IMPROVEMENT_STAGING_OCI_EXECUTION_ENABLED",False)),
        "production_deployment_supported":False,
    }


def trigger_ci(*, provider: str, target: str, ref: str, workflow: str | None = None,
               variables: Dict[str,str] | None = None) -> Dict[str, Any]:
    provider=str(provider or "").lower(); target=_safe_name(target,label="CI target"); ref=_safe_name(ref,label="CI ref")
    execute=bool(getattr(settings,"IMPROVEMENT_STAGING_CI_TRIGGER_ENABLED",False))
    if provider=="github_actions":
        workflow=_safe_name(workflow or str(getattr(settings,"IMPROVEMENT_STAGING_GITHUB_WORKFLOW","staging.yml")),label="workflow")
        payload={"ref":ref,"inputs":{str(k):str(v) for k,v in (variables or {}).items()}}
        url=f"https://api.github.com/repos/{target}/actions/workflows/{quote(workflow,safe='')}/dispatches"
        if not execute: return {"status":"planned","provider":provider,"target":target,"ref":ref,"workflow":workflow}
        token=get_secret("IMPROVEMENT_GITHUB_ACTIONS_TOKEN") or get_secret("IMPROVEMENT_GITHUB_STATUS_TOKEN")
        if not token: raise ValueError("GitHub Actions token is not configured")
        response=httpx.post(url,json=payload,headers={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json"},timeout=10.0)
        if response.status_code not in {200,201,202,204}: raise RuntimeError(f"GitHub Actions dispatch failed: HTTP {response.status_code}")
        return {"status":"triggered","provider":provider,"target":target,"ref":ref,"workflow":workflow,"http_status":response.status_code}
    if provider=="gitlab_pipeline":
        payload={"ref":ref, **{f"variables[{k}]":str(v) for k,v in (variables or {}).items()}}
        base=str(getattr(settings,"IMPROVEMENT_GITLAB_API_BASE","https://gitlab.com/api/v4")).rstrip("/")
        url=f"{base}/projects/{quote(target,safe='')}/pipeline"
        if not execute: return {"status":"planned","provider":provider,"target":target,"ref":ref}
        token=get_secret("IMPROVEMENT_GITLAB_PIPELINE_TOKEN") or get_secret("IMPROVEMENT_GITLAB_STATUS_TOKEN")
        if not token: raise ValueError("GitLab pipeline token is not configured")
        response=httpx.post(url,data=payload,headers={"PRIVATE-TOKEN":token},timeout=10.0)
        if response.status_code not in {200,201,202}: raise RuntimeError(f"GitLab pipeline trigger failed: HTTP {response.status_code}")
        body=response.json() if response.content else {}
        return {"status":"triggered","provider":provider,"target":target,"ref":ref,"pipeline_id":body.get("id"),"web_url":body.get("web_url")}
    raise ValueError("provider must be github_actions or gitlab_pipeline")


def build_deployment_manifest(*, provider: str, release_id: str, image_ref: str | None = None,
                              namespace: str = "ai-staging", cluster: str | None = None,
                              service: str | None = None, task_definition: str | None = None) -> Dict[str, Any]:
    provider=str(provider or "external").lower()
    if provider=="external":
        return {"provider":"external","release_id":release_id,"environment":"staging","production":False}
    if provider=="kubernetes":
        ns=_safe_name(namespace,label="Kubernetes namespace")
        image=_safe_name(image_ref or "",label="OCI image")
        name="aca-staging-"+release_id[:8]
        return {"provider":"kubernetes","release_id":release_id,"environment":"staging","namespace":ns,
                "resources":[{"apiVersion":"apps/v1","kind":"Deployment","metadata":{"name":name,"namespace":ns,"labels":{"app":name,"managed-by":"ai-coding-assistant","environment":"staging"}},
                              "spec":{"replicas":1,"selector":{"matchLabels":{"app":name}},"template":{"metadata":{"labels":{"app":name,"environment":"staging"}},
                              "spec":{"containers":[{"name":"app","image":image,"imagePullPolicy":"IfNotPresent"}]}}}}],"production":False}
    if provider=="ecs":
        c=_safe_name(cluster or "",label="ECS cluster"); s=_safe_name(service or "",label="ECS service"); td=_safe_name(task_definition or "",label="ECS task definition")
        return {"provider":"ecs","release_id":release_id,"environment":"staging","cluster":c,"service":s,"task_definition":td,"production":False}
    raise ValueError("provider must be external, kubernetes, or ecs")


def execute_deployment(manifest: Dict[str,Any], *, manifest_path: str | None = None) -> Dict[str,Any]:
    provider=str(manifest.get("provider") or "")
    if not bool(getattr(settings,"IMPROVEMENT_STAGING_EXECUTION_ENABLED",False)):
        return {"status":"planned","provider":provider,"production":False}
    if provider=="external": return {"status":"ready","provider":provider,"production":False}
    if provider=="kubernetes":
        if not manifest_path: raise ValueError("Kubernetes execution requires a generated manifest file")
        namespace=_safe_name(str(manifest.get("namespace") or ""),label="Kubernetes namespace")
        proc=subprocess.run(["kubectl","apply","-f",manifest_path,"-n",namespace],shell=False,capture_output=True,text=True,timeout=120)
        if proc.returncode!=0: raise RuntimeError((proc.stderr or "kubectl apply failed")[-2000:])
        return {"status":"ready","provider":provider,"deployment_ref":f"k8s:{namespace}:{manifest['resources'][0]['metadata']['name']}","stdout":(proc.stdout or "")[-4000:],"production":False}
    if provider=="ecs":
        cluster=_safe_name(str(manifest.get("cluster") or ""),label="ECS cluster"); service=_safe_name(str(manifest.get("service") or ""),label="ECS service"); td=_safe_name(str(manifest.get("task_definition") or ""),label="ECS task definition")
        proc=subprocess.run(["aws","ecs","update-service","--cluster",cluster,"--service",service,"--task-definition",td,"--force-new-deployment","--output","json"],shell=False,capture_output=True,text=True,timeout=120)
        if proc.returncode!=0: raise RuntimeError((proc.stderr or "ECS staging deployment failed")[-2000:])
        try: body=json.loads(proc.stdout or "{}")
        except Exception: body={}
        return {"status":"ready","provider":provider,"deployment_ref":str((body.get("service") or {}).get("serviceArn") or f"ecs:{cluster}:{service}"),"production":False}
    raise ValueError("Unsupported staging deployment provider")


def rollback_deployment(manifest: Dict[str,Any], *, manifest_path: str | None = None) -> Dict[str,Any]:
    provider=str(manifest.get("provider") or "")
    if not bool(getattr(settings,"IMPROVEMENT_STAGING_EXECUTION_ENABLED",False)):
        return {"status":"rolled_back","provider":provider,"execution":"not_enabled","production":False}
    if provider=="kubernetes":
        if not manifest_path: raise ValueError("Kubernetes rollback requires manifest path")
        ns=_safe_name(str(manifest.get("namespace") or ""),label="Kubernetes namespace")
        proc=subprocess.run(["kubectl","delete","-f",manifest_path,"-n",ns,"--ignore-not-found=true"],shell=False,capture_output=True,text=True,timeout=120)
        if proc.returncode!=0: raise RuntimeError((proc.stderr or "kubectl delete failed")[-2000:])
    elif provider=="ecs":
        # ECS rollback target selection is deployment-specific. We deliberately stop the
        # orchestrator record and require the existing service deployment policy to restore.
        return {"status":"rollback_requested","provider":provider,"reason":"ecs_previous_task_definition_is_environment_specific","production":False}
    return {"status":"rolled_back","provider":provider,"production":False}


def promote_oci_to_staging(*, source_ref: str, destination_ref: str) -> Dict[str,Any]:
    src=_safe_name(source_ref,label="source OCI image"); dest=_safe_name(destination_ref,label="destination OCI image")
    _reject_production(dest,label="destination OCI image")
    if not bool(getattr(settings,"IMPROVEMENT_STAGING_OCI_EXECUTION_ENABLED",False)):
        return {"status":"planned","source_ref":src,"destination_ref":dest,"production":False}
    outputs=[]
    for args in (["docker","pull",src],["docker","tag",src,dest],["docker","push",dest]):
        proc=subprocess.run(args,shell=False,capture_output=True,text=True,timeout=max(60,int(getattr(settings,"IMPROVEMENT_RELEASE_BUILD_TIMEOUT_SECONDS",900))))
        outputs.append({"args":args[:2],"exit_code":proc.returncode,"stderr":(proc.stderr or "")[-1000:]})
        if proc.returncode!=0: raise RuntimeError((proc.stderr or "OCI staging promotion failed")[-2000:])
    return {"status":"promoted","source_ref":src,"destination_ref":dest,"steps":outputs,"production":False}
