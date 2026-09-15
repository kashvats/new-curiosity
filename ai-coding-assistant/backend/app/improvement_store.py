"""Persistence for manual self-improvement cycles, candidates, events and outcomes."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from app.database import get_db, init_database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def create_improvement_cycle(
    *, project_name: str, trigger: str, policy: str, request: Dict[str, Any],
    budget: Dict[str, Any] | None = None, usage: Dict[str, Any] | None = None,
    policy_snapshot: Dict[str, Any] | None = None, policy_integrity: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    init_database()
    if not policy_snapshot:
        from app.improvement_policy import resolved_improvement_policy
        policy_snapshot = resolved_improvement_policy(project_name)
    if not policy_integrity:
        from app.improvement_integrity import seal_policy_snapshot
        policy_integrity = seal_policy_snapshot(policy_snapshot)
    cycle_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_cycles
               (id, project_name, trigger, state, policy, request_json, budget_json, usage_json, policy_snapshot_json, policy_integrity_json, started_at)
               VALUES (?, ?, ?, 'IDLE', ?, ?, ?, ?, ?, ?, ?)""",
            (
                cycle_id, project_name, trigger, policy,
                json.dumps(request, ensure_ascii=False, default=str),
                json.dumps(budget or {}, ensure_ascii=False, default=str),
                json.dumps(usage or {}, ensure_ascii=False, default=str),
                json.dumps(policy_snapshot or {}, ensure_ascii=False, default=str),
                json.dumps(policy_integrity or {}, ensure_ascii=False, default=str),
                now,
            ),
        )
        conn.commit()
    append_improvement_event(cycle_id, "cycle_created", state="IDLE", message=f"Improvement cycle created ({policy})")
    return get_improvement_cycle(cycle_id) or {"id": cycle_id, "state": "IDLE"}


def update_improvement_cycle(
    cycle_id: str,
    *,
    state: str | None = None,
    baseline_score: float | None = None,
    final_score: float | None = None,
    baseline_snapshot_id: str | None = None,
    final_snapshot_id: str | None = None,
    selected_candidate_id: str | None = None,
    selected_issue_id: str | None = None,
    result: Dict[str, Any] | None = None,
    stop_reason: str | None = None,
    budget: Dict[str, Any] | None = None,
    usage: Dict[str, Any] | None = None,
    policy_snapshot: Dict[str, Any] | None = None,
    policy_integrity: Dict[str, Any] | None = None,
    cancel_requested: bool | None = None,
    cancelled_at: str | None = None,
    mark_completed: bool = False,
) -> Dict[str, Any]:
    init_database()
    fields: list[str] = []
    values: list[Any] = []
    mapping = {
        "state": state,
        "baseline_score": baseline_score,
        "final_score": final_score,
        "baseline_snapshot_id": baseline_snapshot_id,
        "final_snapshot_id": final_snapshot_id,
        "selected_candidate_id": selected_candidate_id,
        "selected_issue_id": selected_issue_id,
        "stop_reason": stop_reason,
    }
    for column, value in mapping.items():
        if value is not None:
            fields.append(f"{column} = ?")
            values.append(value)
    if result is not None:
        fields.append("result_json = ?")
        values.append(json.dumps(result, ensure_ascii=False, default=str))
    if budget is not None:
        fields.append("budget_json = ?")
        values.append(json.dumps(budget, ensure_ascii=False, default=str))
    if usage is not None:
        fields.append("usage_json = ?")
        values.append(json.dumps(usage, ensure_ascii=False, default=str))
    if policy_snapshot is not None:
        fields.append("policy_snapshot_json = ?")
        values.append(json.dumps(policy_snapshot, ensure_ascii=False, default=str))
    if policy_integrity is not None:
        fields.append("policy_integrity_json = ?")
        values.append(json.dumps(policy_integrity, ensure_ascii=False, default=str))
    if cancel_requested is not None:
        fields.append("cancel_requested = ?")
        values.append(1 if cancel_requested else 0)
    if cancelled_at is not None:
        fields.append("cancelled_at = ?")
        values.append(cancelled_at)
    if mark_completed:
        fields.append("completed_at = ?")
        values.append(_now())
    if not fields:
        return get_improvement_cycle(cycle_id) or {}
    values.append(cycle_id)
    with get_db() as conn:
        conn.execute("UPDATE improvement_cycles SET " + ", ".join(fields) + " WHERE id = ?", tuple(values))
        conn.commit()
    return get_improvement_cycle(cycle_id) or {}


def get_improvement_cycle(cycle_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_cycles WHERE id = ?", (cycle_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["request"] = _loads(item.pop("request_json", None), {})
    item["result"] = _loads(item.pop("result_json", None), None)
    item["budget"] = _loads(item.pop("budget_json", None), {})
    item["usage"] = _loads(item.pop("usage_json", None), {})
    item["policy_snapshot"] = _loads(item.pop("policy_snapshot_json", None), {})
    item["policy_integrity"] = _loads(item.pop("policy_integrity_json", None), {})
    item["cancel_requested"] = bool(item.get("cancel_requested"))
    return item


def list_improvement_cycles(*, project_name: str | None = None, limit: int = 50) -> List[Dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 200))
    with get_db() as conn:
        if project_name:
            rows = conn.execute(
                "SELECT * FROM improvement_cycles WHERE project_name = ? ORDER BY started_at DESC LIMIT ?",
                (project_name, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM improvement_cycles ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["request"] = _loads(item.pop("request_json", None), {})
        item["result"] = _loads(item.pop("result_json", None), None)
        item["budget"] = _loads(item.pop("budget_json", None), {})
        item["usage"] = _loads(item.pop("usage_json", None), {})
        item["policy_snapshot"] = _loads(item.pop("policy_snapshot_json", None), {})
        item["policy_integrity"] = _loads(item.pop("policy_integrity_json", None), {})
        item["cancel_requested"] = bool(item.get("cancel_requested"))
        output.append(item)
    return output


def append_improvement_event(
    cycle_id: str,
    event_type: str,
    *,
    state: str | None = None,
    message: str = "",
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    init_database()
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO improvement_events
               (cycle_id, event_type, state, message, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cycle_id, event_type, state, message, json.dumps(payload or {}, ensure_ascii=False, default=str), now),
        )
        conn.commit()
        seq = int(cur.lastrowid)
    return {"seq": seq, "cycle_id": cycle_id, "event_type": event_type, "state": state, "message": message, "payload": payload or {}, "created_at": now}


def list_improvement_events(cycle_id: str, *, after_seq: int = 0, limit: int = 200) -> List[Dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 1000))
    with get_db() as conn:
        rows = conn.execute(
            """SELECT seq, cycle_id, event_type, state, message, payload_json, created_at
               FROM improvement_events WHERE cycle_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?""",
            (cycle_id, int(after_seq), limit),
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["payload"] = _loads(item.pop("payload_json", None), {})
        output.append(item)
    return output


def store_health_snapshot(*, project_name: str, snapshot: Dict[str, Any], cycle_id: str | None, phase: str) -> Dict[str, Any]:
    init_database()
    snapshot_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO project_health_snapshots
               (id, project_name, cycle_id, phase, health_score, dimensions_json, findings_json, checks_json, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_id, project_name, cycle_id, phase, float(snapshot.get("health_score") or 0.0),
                json.dumps(snapshot.get("dimensions", {}), ensure_ascii=False, default=str),
                json.dumps(snapshot.get("findings", []), ensure_ascii=False, default=str),
                json.dumps(snapshot.get("checks", {}), ensure_ascii=False, default=str),
                json.dumps(snapshot.get("metadata", {}), ensure_ascii=False, default=str), now,
            ),
        )
        conn.commit()
    return get_health_snapshot(snapshot_id) or {"id": snapshot_id, **snapshot}


def get_health_snapshot(snapshot_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM project_health_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    for raw, clean, default in (
        ("dimensions_json", "dimensions", {}), ("findings_json", "findings", []),
        ("checks_json", "checks", {}), ("metadata_json", "metadata", {}),
    ):
        item[clean] = _loads(item.pop(raw, None), default)
    return item


def latest_health_snapshot(project_name: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM project_health_snapshots WHERE project_name = ? ORDER BY created_at DESC LIMIT 1",
            (project_name,),
        ).fetchone()
    return get_health_snapshot(row["id"]) if row else None


def store_improvement_candidates(cycle_id: str, candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    init_database()
    now = _now()
    ids: list[str] = []
    with get_db() as conn:
        for candidate in candidates:
            candidate_id = str(candidate.get("id") or uuid.uuid4())
            ids.append(candidate_id)
            conn.execute(
                """INSERT OR REPLACE INTO improvement_candidates
                   (id, cycle_id, problem, evidence_json, proposal, risk, benefit, confidence, urgency,
                    estimated_cost, priority_score, likely_files_json, validation_plan_json, issue_id,
                    status, strategy_key, base_priority_score, learning_multiplier, history_samples,
                    history_success_rate, history_average_score_delta, candidate_fingerprint, suppressed,
                    suppression_reason, repeat_count, impact_memory_json, base_risk, cooldown_until, cooldown_reason,
                    risk_escalation_json, production_history_samples, production_failure_rate, production_rollbacks,
                    production_learning_multiplier, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           COALESCE((SELECT created_at FROM improvement_candidates WHERE id=?), ?), ?)""",
                (
                    candidate_id, cycle_id, candidate.get("problem", ""),
                    json.dumps(candidate.get("evidence", {}), ensure_ascii=False, default=str), candidate.get("proposal", ""),
                    candidate.get("risk", "medium"), float(candidate.get("benefit") or 0.0), float(candidate.get("confidence") or 0.0),
                    float(candidate.get("urgency") or 0.0), float(candidate.get("estimated_cost") or 1.0), float(candidate.get("priority_score") or 0.0),
                    json.dumps(candidate.get("likely_files", []), ensure_ascii=False, default=str),
                    json.dumps(candidate.get("validation_plan", []), ensure_ascii=False, default=str),
                    candidate.get("issue_id"), candidate.get("status", "proposed"), candidate.get("strategy_key"),
                    float(candidate.get("base_priority_score") if candidate.get("base_priority_score") is not None else candidate.get("priority_score") or 0.0),
                    float(candidate.get("learning_multiplier") or 1.0), int(candidate.get("history_samples") or 0),
                    float(candidate.get("history_success_rate") or 0.0), float(candidate.get("history_average_score_delta") or 0.0),
                    candidate.get("candidate_fingerprint"), 1 if candidate.get("suppressed") else 0, candidate.get("suppression_reason"),
                    int(candidate.get("repeat_count") or 0), json.dumps(candidate.get("impact_memory", {}), ensure_ascii=False, default=str),
                    candidate.get("base_risk") or candidate.get("risk", "medium"), candidate.get("cooldown_until"), candidate.get("cooldown_reason"),
                    json.dumps(candidate.get("risk_escalation", {}), ensure_ascii=False, default=str),
                    int(candidate.get("production_history_samples") or 0), float(candidate.get("production_failure_rate") or 0.0),
                    int(candidate.get("production_rollbacks") or 0), float(candidate.get("production_learning_multiplier") or 1.0),
                    candidate_id, now, now,
                ),
            )
        conn.commit()
    return [item for item in (get_improvement_candidate(cid) for cid in ids) if item]

def _candidate_from_row(row: Any) -> Dict[str, Any]:
    item = dict(row)
    item["evidence"] = _loads(item.pop("evidence_json", None), {})
    item["likely_files"] = _loads(item.pop("likely_files_json", None), [])
    item["validation_plan"] = _loads(item.pop("validation_plan_json", None), [])
    item["impact_memory"] = _loads(item.pop("impact_memory_json", None), {})
    item["risk_escalation"] = _loads(item.pop("risk_escalation_json", None), {})
    item["suppressed"] = bool(item.get("suppressed"))
    return item


def get_improvement_candidate(candidate_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_candidates WHERE id = ?", (candidate_id,)).fetchone()
    return _candidate_from_row(row) if row else None


def list_improvement_candidates(cycle_id: str) -> List[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM improvement_candidates WHERE cycle_id = ? ORDER BY priority_score DESC, created_at ASC",
            (cycle_id,),
        ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def update_improvement_candidate(candidate_id: str, *, status: str | None = None, issue_id: str | None = None) -> Dict[str, Any]:
    init_database()
    fields = ["updated_at = ?"]
    values: list[Any] = [_now()]
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if issue_id is not None:
        fields.append("issue_id = ?")
        values.append(issue_id)
    values.append(candidate_id)
    with get_db() as conn:
        conn.execute("UPDATE improvement_candidates SET " + ", ".join(fields) + " WHERE id = ?", tuple(values))
        conn.commit()
    return get_improvement_candidate(candidate_id) or {}


def store_improvement_outcome(
    *,
    cycle_id: str,
    candidate_id: str | None,
    issue_id: str | None,
    project_name: str,
    apply_status: str,
    baseline_score: float | None,
    final_score: float | None,
    baseline_snapshot_id: str | None,
    final_snapshot_id: str | None,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    init_database()
    outcome_id = str(uuid.uuid4())
    now = _now()
    delta = None if baseline_score is None or final_score is None else round(float(final_score) - float(baseline_score), 2)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_outcomes
               (id, cycle_id, candidate_id, issue_id, project_name, apply_status, baseline_score, final_score,
                score_delta, baseline_snapshot_id, final_snapshot_id, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (outcome_id, cycle_id, candidate_id, issue_id, project_name, apply_status, baseline_score, final_score,
             delta, baseline_snapshot_id, final_snapshot_id, json.dumps(details, ensure_ascii=False, default=str), now),
        )
        conn.commit()
    return get_improvement_outcome(outcome_id) or {"id": outcome_id, "score_delta": delta}


def get_improvement_outcome(outcome_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_outcomes WHERE id = ?", (outcome_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["details"] = _loads(item.pop("details_json", None), {})
    return item


def list_improvement_outcomes(*, project_name: str | None = None, cycle_id: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 500))
    query = "SELECT * FROM improvement_outcomes"
    args: list[Any] = []
    clauses: list[str] = []
    if project_name:
        clauses.append("project_name = ?")
        args.append(project_name)
    if cycle_id:
        clauses.append("cycle_id = ?")
        args.append(cycle_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(query, tuple(args)).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["details"] = _loads(item.pop("details_json", None), {})
        output.append(item)
    return output


def store_improvement_experiment(
    *, cycle_id: str, candidate_id: str, issue_id: str | None, experiment_rank: int,
    status: str, quality_score: float | None, usage: Dict[str, Any], result: Dict[str, Any],
) -> Dict[str, Any]:
    init_database()
    experiment_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO improvement_experiments
               (id, cycle_id, candidate_id, issue_id, experiment_rank, status, quality_score, usage_json, result_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                experiment_id, cycle_id, candidate_id, issue_id, int(experiment_rank), status, quality_score,
                json.dumps(usage or {}, ensure_ascii=False, default=str),
                json.dumps(result or {}, ensure_ascii=False, default=str), now,
            ),
        )
        conn.commit()
    return get_improvement_experiment(experiment_id) or {"id": experiment_id}


def get_improvement_experiment(experiment_id: str) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM improvement_experiments WHERE id = ?", (experiment_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["usage"] = _loads(item.pop("usage_json", None), {})
    item["result"] = _loads(item.pop("result_json", None), {})
    return item


def list_improvement_experiments(cycle_id: str) -> List[Dict[str, Any]]:
    init_database()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM improvement_experiments WHERE cycle_id = ? ORDER BY experiment_rank ASC, created_at ASC",
            (cycle_id,),
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["usage"] = _loads(item.pop("usage_json", None), {})
        item["result"] = _loads(item.pop("result_json", None), {})
        output.append(item)
    return output

def discard_improvement_experiment(experiment_id: str) -> Dict[str, Any]:
    init_database()
    now = _now()
    with get_db() as conn:
        row = conn.execute("SELECT candidate_id FROM improvement_experiments WHERE id = ?", (experiment_id,)).fetchone()
        if not row:
            raise KeyError(experiment_id)
        full = conn.execute("SELECT issue_id FROM improvement_experiments WHERE id = ?", (experiment_id,)).fetchone()
        conn.execute("UPDATE improvement_experiments SET status = 'discarded', discarded_at = ? WHERE id = ?", (now, experiment_id))
        conn.execute("UPDATE improvement_candidates SET status = 'discarded', updated_at = ? WHERE id = ? AND status != 'applied'", (now, row["candidate_id"]))
        conn.commit()
    issue_id = full["issue_id"] if full else None
    if issue_id:
        try:
            from app.verified_candidate_store import discard_verified_repair
            discard_verified_repair(issue_id, reason="Improvement experiment discarded by user")
        except (KeyError, ValueError):
            pass
    return get_improvement_experiment(experiment_id) or {"id": experiment_id, "status": "discarded", "discarded_at": now}


def request_improvement_cycle_cancel(cycle_id: str) -> Dict[str, Any]:
    cycle = get_improvement_cycle(cycle_id)
    if not cycle:
        raise KeyError(cycle_id)
    if cycle.get("completed_at"):
        return cycle
    now = _now()
    immediate = cycle.get("state") in {"IDLE", "WAITING_SELECTION", "WAITING_APPROVAL", "VALIDATION_FAILED", "BUDGET_EXCEEDED", "BLOCKED_BY_CAPABILITY"}
    if immediate:
        issue_id = cycle.get("selected_issue_id")
        if issue_id:
            try:
                from app.verified_candidate_store import discard_verified_repair
                discard_verified_repair(issue_id, reason="Improvement cycle cancelled by user")
            except (KeyError, ValueError):
                pass
        return update_improvement_cycle(
            cycle_id, state="CANCELLED", result={"status": "cancelled"}, stop_reason="cancelled_by_user",
            cancel_requested=True, cancelled_at=now, mark_completed=True,
        )
    return update_improvement_cycle(cycle_id, state="CANCEL_REQUESTED", cancel_requested=True)



def update_improvement_experiment_status(cycle_id: str, candidate_id: str, *, status: str, result_patch: Dict[str, Any] | None = None) -> Dict[str, Any] | None:
    init_database()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM improvement_experiments WHERE cycle_id = ? AND candidate_id = ? ORDER BY experiment_rank DESC LIMIT 1",
            (cycle_id, candidate_id),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        result = _loads(item.get("result_json"), {})
        if result_patch:
            result.update(result_patch)
        conn.execute(
            "UPDATE improvement_experiments SET status = ?, result_json = ? WHERE id = ?",
            (status, json.dumps(result, ensure_ascii=False, default=str), item["id"]),
        )
        conn.commit()
    return get_improvement_experiment(item["id"])
