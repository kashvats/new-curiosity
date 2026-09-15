"""Part 8 dry-run guarded scheduler.

This scheduler is intentionally incapable of applying source changes. Scheduled
`observe_propose` runs always create an `observe_only` improvement cycle. Canary
runs capture health only. Live source promotion remains exclusively manual.
"""
from __future__ import annotations

import asyncio
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.config import settings
from app.improvement_budget import empty_usage, resolve_cycle_budget
from app.improvement_controller import run_improvement_cycle
from app.improvement_integrity import seal_policy_snapshot
from app.improvement_policy import resolved_improvement_policy
from app.improvement_scheduler_guards import evaluate_schedule_guards
from app.improvement_scheduler_observability import create_scheduler_alert, record_scheduler_telemetry
from app.improvement_scheduler_integrations import flush_integrations, integration_status
from app.improvement_scheduler_ha import (
    acquire_scheduler_lease, coordination_status, heartbeat_scheduler_lease,
    release_scheduler_lease, validate_scheduler_lease,
)
from app.improvement_scheduler_security import operator_auth_configured, signed_webhook_configured
from app.improvement_scheduler_tracing import new_trace_id, record_span
from app.improvement_scheduler_store import (
    advance_schedule,
    attach_scheduler_cycle,
    create_scheduler_run,
    due_schedules,
    finish_scheduler_run,
    get_schedule,
    get_scheduler_control,
    list_scheduler_runs,
    list_schedules,
)
from app.improvement_store import create_improvement_cycle, store_health_snapshot
from app.project_health import capture_project_health

_ALLOWED_MODES = {"observe_propose", "canary_observe"}


def scheduler_owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def scheduler_status() -> Dict[str, Any]:
    global_control = get_scheduler_control("global")
    return {
        "control_plane_available": True,
        "background_scheduler_enabled": bool(settings.IMPROVEMENT_DRY_RUN_SCHEDULER_ENABLED),
        "kill_switch": bool(global_control.get("kill_switch")),
        "kill_switch_reason": global_control.get("reason"),
        "owner_id": scheduler_owner_id(),
        "allowed_modes": sorted(_ALLOWED_MODES),
        "scheduled_source_apply_enabled": False,
        "automatic_source_apply_enabled": False,
        "human_apply_boundary_unchanged": True,
        "poll_seconds": int(settings.IMPROVEMENT_SCHEDULER_POLL_SECONDS),
        "signed_webhook_configured": signed_webhook_configured(),
        "operator_registry_configured": operator_auth_configured(),
        "lease_fencing_enabled": True,
        "part9_production_hardening": True,
        "part10_deployment_hardening": True,
        "part11_deployment_packaging": True,
        "coordination": coordination_status(),
        "integrations": integration_status(),
    }


async def _heartbeat(leases: Dict[str, int], owner_id: str, stop: asyncio.Event) -> None:
    ttl = max(15, int(settings.IMPROVEMENT_SCHEDULER_LEASE_TTL_SECONDS))
    delay = max(5, ttl // 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            break
        except asyncio.TimeoutError:
            for key, fence_token in leases.items():
                heartbeat_scheduler_lease(key, owner_id=owner_id, ttl_seconds=ttl, fence_token=fence_token)


async def _leader_heartbeat(owner_id: str, fence_token: int, ttl: int, stop: asyncio.Event) -> None:
    delay = max(5, int(ttl) // 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            break
        except asyncio.TimeoutError:
            if not heartbeat_scheduler_lease("scheduler:leader", owner_id=owner_id, ttl_seconds=ttl, fence_token=fence_token):
                break


def _safe_observe_request(schedule: Dict[str, Any]) -> Dict[str, Any]:
    source = dict(schedule.get("request") or {})
    # The scheduler owns these fields. A persisted request cannot escalate itself
    # into a repair/apply workflow.
    safe = {
        "project_name": schedule["project_name"],
        "trigger": f"scheduler:{schedule['id']}",
        "policy": "observe_only",
        "run_checks": bool(source.get("run_checks", True)),
        "force": bool(source.get("force", False)),
        "allowed_risks": list(source.get("allowed_risks") or ["low", "medium"]),
        "min_priority": source.get("min_priority"),
        "acceptable_health_score": source.get("acceptable_health_score"),
        "pause_for_candidate_selection": False,
        "experiment_mode": False,
        "experiment_candidates": 1,
    }
    return safe


def simulate_schedule(schedule: Dict[str, Any], *, now: datetime | None = None, include_readiness: bool = True) -> Dict[str, Any]:
    """Preview all deterministic gates without creating a run, lease, cycle, or evidence."""
    preview = dict(schedule)
    preview.setdefault("id", "__preview__")
    preview.setdefault("environment", "dev")
    decision = evaluate_schedule_guards(preview, now=now, include_readiness=include_readiness)
    return {
        "simulation": True,
        "schedule": preview,
        "decision": decision,
        "would_run": bool(decision.get("passed")),
        "scheduled_source_apply_enabled": False,
        "automatic_source_apply_enabled": False,
    }


async def run_schedule(schedule_id: str, *, ignore_due: bool = False, now: datetime | None = None) -> Dict[str, Any]:
    schedule = get_schedule(schedule_id)
    if not schedule:
        raise KeyError(schedule_id)
    if not schedule.get("enabled"):
        return {"status": "skipped", "reason": "schedule_disabled", "schedule_id": schedule_id}
    if schedule.get("mode") not in _ALLOWED_MODES:
        return {"status": "blocked", "reason": "unsupported_schedule_mode", "schedule_id": schedule_id}

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    next_run = schedule.get("next_run_at")
    if not ignore_due and next_run:
        try:
            due = datetime.fromisoformat(str(next_run).replace("Z", "+00:00"))
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if due > current:
                return {"status": "skipped", "reason": "not_due", "schedule_id": schedule_id, "next_run_at": next_run}
        except Exception:
            pass

    owner = f"{scheduler_owner_id()}:{uuid.uuid4()}"
    run = create_scheduler_run(schedule_id=schedule_id, project_name=schedule["project_name"], mode=schedule["mode"])
    run_id = run["id"]
    trace_id = new_trace_id()
    root_span_id = uuid.uuid4().hex[:16]
    started_perf = time.perf_counter()
    ttl = max(15, int(settings.IMPROVEMENT_SCHEDULER_LEASE_TTL_SECONDS))
    lease_keys = ["scheduler:global", f"scheduler:project:{schedule['project_name']}"]
    acquired: Dict[str, int] = {}

    def complete(status: str, decision: Dict[str, Any], cycle_id: str | None = None) -> Dict[str, Any]:
        duration_ms = (time.perf_counter() - started_perf) * 1000.0
        final = finish_scheduler_run(run_id, status=status, decision=decision, cycle_id=cycle_id)
        record_scheduler_telemetry(
            event_type="scheduler_run", project_name=schedule["project_name"], schedule_id=schedule_id,
            run_id=run_id, duration_ms=duration_ms, attributes={"status": status, "mode": schedule.get("mode"), "environment": schedule.get("environment", "dev")},
        )
        record_span(
            trace_id=trace_id, span_id=root_span_id, name="scheduler.run", project_name=schedule["project_name"],
            schedule_id=schedule_id, run_id=run_id, status="error" if status == "error" else "ok",
            duration_ms=duration_ms, attributes={"status": status, "mode": schedule.get("mode"), "environment": schedule.get("environment", "dev")},
        )
        if status in {"blocked", "error", "canary_failed"}:
            severity = "error" if status == "error" else "warning"
            code = "scheduler_error" if status == "error" else ("canary_failed" if status == "canary_failed" else "scheduler_blocked")
            message = str(decision.get("error") or decision.get("reason") or (decision.get("blockers") or [{}])[0].get("message") or status)
            create_scheduler_alert(
                project_name=schedule["project_name"], schedule_id=schedule_id, run_id=run_id,
                severity=severity, code=code, message=message, details={"decision": decision, "environment": schedule.get("environment", "dev")},
            )
        return final
    stop_heartbeat = asyncio.Event()
    heartbeat_task: asyncio.Task | None = None

    try:
        lease_started = time.perf_counter()
        for key in lease_keys:
            result = acquire_scheduler_lease(key, owner_id=owner, ttl_seconds=ttl)
            if not result.get("acquired"):
                decision = {"passed": False, "blockers": [{"name": "concurrency_lease", "passed": False, "message": f"Lease busy: {key}", "evidence": result}]}
                return complete("blocked", decision)
            acquired[key] = int(result.get("fence_token") or 0)
        record_span(trace_id=trace_id, name="scheduler.leases.acquire", project_name=schedule["project_name"],
                    schedule_id=schedule_id, run_id=run_id, parent_span_id=root_span_id, duration_ms=(time.perf_counter()-lease_started)*1000.0,
                    attributes={"lease_keys": lease_keys, "backend": coordination_status().get("lease_backend")})
        heartbeat_task = asyncio.create_task(_heartbeat(acquired, owner, stop_heartbeat))

        if not all(validate_scheduler_lease(key, owner_id=owner, fence_token=token) for key, token in acquired.items()):
            decision = {"passed": False, "blockers": [{"name": "lease_fencing", "passed": False, "message": "Scheduler lease fencing validation failed"}]}
            return complete("blocked", decision)

        guard_started = time.perf_counter()
        decision = evaluate_schedule_guards(schedule, now=current)
        record_span(trace_id=trace_id, name="scheduler.guards", project_name=schedule["project_name"],
                    schedule_id=schedule_id, run_id=run_id, parent_span_id=root_span_id, duration_ms=(time.perf_counter()-guard_started)*1000.0,
                    status="ok" if decision.get("passed") else "blocked", attributes={"passed": bool(decision.get("passed")), "blocker_count": len(decision.get("blockers") or [])})
        if not decision.get("passed"):
            return complete("blocked", decision)

        if schedule["mode"] == "canary_observe":
            health_started = time.perf_counter()
            health = capture_project_health(schedule["project_name"], run_checks=bool((schedule.get("request") or {}).get("run_checks", False)))
            record_span(trace_id=trace_id, name="scheduler.canary.health", project_name=schedule["project_name"],
                        schedule_id=schedule_id, run_id=run_id, parent_span_id=root_span_id, duration_ms=(time.perf_counter()-health_started)*1000.0,
                        attributes={"health_score": health.get("health_score")})
            stored = store_health_snapshot(project_name=schedule["project_name"], snapshot=health, cycle_id=None, phase="scheduler_canary")
            score = float(health.get("health_score") or 0.0)
            canary_passed = score >= float(settings.IMPROVEMENT_SCHEDULER_CANARY_MIN_HEALTH)
            canary = {
                **decision,
                "canary": {"passed": canary_passed, "health_score": score, "minimum": settings.IMPROVEMENT_SCHEDULER_CANARY_MIN_HEALTH, "snapshot_id": stored["id"]},
                "scheduled_source_apply_enabled": False,
            }
            return complete("canary_passed" if canary_passed else "canary_failed", canary)

        if not all(validate_scheduler_lease(key, owner_id=owner, fence_token=token) for key, token in acquired.items()):
            decision = {**decision, "passed": False, "blockers": [{"name": "lease_fencing", "passed": False, "message": "Scheduler lost its fenced lease before cycle creation"}]}
            return complete("blocked", decision)

        request = _safe_observe_request(schedule)
        budget = resolve_cycle_budget(request)
        policy_snapshot = resolved_improvement_policy(schedule["project_name"])
        cycle = create_improvement_cycle(
            project_name=schedule["project_name"], trigger=request["trigger"], policy="observe_only",
            request=request, budget=budget, usage=empty_usage(), policy_snapshot=policy_snapshot,
            policy_integrity=seal_policy_snapshot(policy_snapshot),
        )
        attach_scheduler_cycle(run_id, cycle["id"])
        cycle_started = time.perf_counter()
        completed = await run_improvement_cycle(cycle["id"])
        record_span(trace_id=trace_id, name="scheduler.observe_cycle", project_name=schedule["project_name"],
                    schedule_id=schedule_id, run_id=run_id, parent_span_id=root_span_id, duration_ms=(time.perf_counter()-cycle_started)*1000.0,
                    attributes={"cycle_id": cycle["id"], "cycle_state": completed.get("state")})
        result = {
            **decision,
            "cycle_state": completed.get("state"),
            "cycle_stop_reason": completed.get("stop_reason"),
            "cycle_result_status": (completed.get("result") or {}).get("status"),
            "scheduled_policy": "observe_only",
            "scheduled_source_apply_enabled": False,
        }
        return complete("completed", result, cycle["id"])
    except Exception as exc:
        return complete("error", {"passed": False, "error": str(exc), "scheduled_source_apply_enabled": False})
    finally:
        advance_schedule(schedule_id, interval_minutes=int(schedule.get("interval_minutes") or 1440), ran_at=current.isoformat())
        stop_heartbeat.set()
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        for key in reversed(list(acquired.keys())):
            release_scheduler_lease(key, owner_id=owner, fence_token=acquired[key])


async def scheduler_tick(*, limit: int = 20) -> Dict[str, Any]:
    schedules = due_schedules(limit=max(1, min(int(limit), 100)))
    results: list[Dict[str, Any]] = []
    for schedule in schedules:
        results.append(await run_schedule(schedule["id"]))
    integration_result = None
    try:
        integration_result = flush_integrations(limit=100)
    except Exception as exc:
        integration_result = {"error": str(exc)[:500]}
    preview_teardown = {"enabled": False}
    if bool(getattr(settings, "IMPROVEMENT_STAGING_AUTO_TEARDOWN_EXPIRED", False)):
        try:
            from app.improvement_staging_orchestrator import teardown_expired_previews
            preview_teardown = {"enabled": True, **teardown_expired_previews()}
        except Exception as exc:
            preview_teardown = {"enabled": True, "error": str(exc)[:500]}
    return {
        "status": "completed",
        "due": len(schedules),
        "runs": results,
        "integrations": integration_result,
        "preview_teardown": preview_teardown,
        "automatic_source_apply_enabled": False,
    }


async def scheduler_worker_loop() -> None:
    """Optional background poller with fenced leader election.

    Leader election coordinates scheduler polling only. It never grants source-apply
    authority and every scheduled cycle remains observe-only/canary-only.
    """
    leader_owner = f"{scheduler_owner_id()}:leader:{uuid.uuid4()}"
    leader_token: int | None = None
    ttl = max(15, int(getattr(settings, "IMPROVEMENT_SCHEDULER_LEADER_LEASE_TTL_SECONDS", 120)))
    try:
        while True:
            try:
                enabled = bool(settings.IMPROVEMENT_DRY_RUN_SCHEDULER_ENABLED)
                clear = not get_scheduler_control("global").get("kill_switch")
                if enabled and clear:
                    if bool(getattr(settings, "IMPROVEMENT_SCHEDULER_LEADER_ELECTION_ENABLED", True)):
                        if leader_token is None or not validate_scheduler_lease("scheduler:leader", owner_id=leader_owner, fence_token=leader_token):
                            result = acquire_scheduler_lease("scheduler:leader", owner_id=leader_owner, ttl_seconds=ttl)
                            leader_token = int(result.get("fence_token") or 0) if result.get("acquired") else None
                        else:
                            heartbeat_scheduler_lease("scheduler:leader", owner_id=leader_owner, ttl_seconds=ttl, fence_token=leader_token)
                        if leader_token is not None:
                            leader_stop = asyncio.Event()
                            leader_task = asyncio.create_task(_leader_heartbeat(leader_owner, leader_token, ttl, leader_stop))
                            try:
                                await scheduler_tick(limit=20)
                            finally:
                                leader_stop.set()
                                leader_task.cancel()
                                try:
                                    await leader_task
                                except asyncio.CancelledError:
                                    pass
                    else:
                        await scheduler_tick(limit=20)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(max(5, int(settings.IMPROVEMENT_SCHEDULER_POLL_SECONDS)))
    finally:
        if leader_token is not None:
            try:
                release_scheduler_lease("scheduler:leader", owner_id=leader_owner, fence_token=leader_token)
            except Exception:
                pass


def scheduler_overview(project_name: str | None = None) -> Dict[str, Any]:
    return {
        "status": scheduler_status(),
        "schedules": list_schedules(project_name=project_name),
        "recent_runs": list_scheduler_runs(project_name=project_name, limit=25),
    }
