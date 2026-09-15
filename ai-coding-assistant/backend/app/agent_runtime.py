"""Shared multi-agent runtime.

Agents are role-specific adapters over existing services. They do not own filesystem
or shell permissions; those are provided by constrained services such as
patch_engine and safe_commands.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional, Protocol


@dataclass
class AgentContext:
    task: str
    project_name: str = ""
    project_root: str = ""
    files: list[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    previous_attempts: list[Dict[str, Any]] = field(default_factory=list)
    extra_context: str = ""


@dataclass
class AgentResult:
    agent: str
    status: str
    data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Agent(Protocol):
    name: str
    async def run(self, context: AgentContext) -> AgentResult: ...


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: Dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        if not getattr(agent, "name", ""):
            raise ValueError("Agent must have a non-empty name")
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise KeyError(f"Agent '{name}' is not registered") from exc

    def names(self) -> list[str]:
        return sorted(self._agents)

    async def run(self, name: str, context: AgentContext) -> AgentResult:
        return await self.get(name).run(context)


class ContextAgent:
    name = "context"

    async def run(self, context: AgentContext) -> AgentResult:
        from app.context_builder import build_ide_context
        data = build_ide_context(
            project_name=context.project_name or "default",
            project_root=context.project_root or None,
            files=context.files,
            current_file=context.evidence.get("current_file"),
            selected_text=context.evidence.get("selected_text", ""),
            diagnostics=context.evidence.get("diagnostics", []),
            terminal_output=context.evidence.get("terminal_output", ""),
            task=context.task,
        )
        return AgentResult(self.name, "ok", data)


class PlannerAgent:
    name = "planner"

    async def run(self, context: AgentContext) -> AgentResult:
        from app.planner import create_plan
        plan = await create_plan(context.task)
        return AgentResult(self.name, "ok", {"plan": plan})


class CoderAgent:
    name = "coder"

    async def run(self, context: AgentContext) -> AgentResult:
        from app.coder import draft_code_changes
        result = await draft_code_changes(
            task=context.task,
            file_paths=context.files,
            extra_context=context.extra_context,
            project_name=context.project_name or "default",
        )
        status = "ok" if result.get("status") != "error" else "error"
        return AgentResult(self.name, status, result, result.get("message", ""))


class DebuggerAgent:
    name = "debugger"

    async def run(self, context: AgentContext) -> AgentResult:
        import json
        from app.model_manager import model_manager, get_effective_model
        prompt = (
            "You are the Debugger Agent. Diagnose the root cause using the exact evidence. "
            "Do not propose broad refactors. Return JSON with keys: diagnosis, next_strategy, "
            "likely_files, confidence.\n\n"
            f"TASK:\n{context.task}\n\n"
            f"EVIDENCE:\n{json.dumps(context.evidence, ensure_ascii=False, default=str)[:24000]}\n\n"
            f"PREVIOUS ATTEMPTS:\n{json.dumps(context.previous_attempts, ensure_ascii=False, default=str)[:24000]}"
        )
        raw = await model_manager.generate_completion(prompt, model=get_effective_model("debugger"), expect_json=True)
        try:
            data = json.loads(raw)
        except Exception:
            data = {"diagnosis": raw, "next_strategy": "targeted_fix", "likely_files": context.files, "confidence": 0.3}
        return AgentResult(self.name, "ok", data)


class ReviewerAgent:
    name = "reviewer"

    async def run(self, context: AgentContext) -> AgentResult:
        from app.reviewer import review_changes
        data = await review_changes(
            task=context.task,
            changes=context.evidence.get("changes", []),
            project_name=context.project_name,
            validation=context.evidence.get("validation"),
        )
        return AgentResult(self.name, "ok" if data.get("approved") else "rejected", data)


class TesterAgent:
    name = "tester"

    async def run(self, context: AgentContext) -> AgentResult:
        from app.verification_service import verification_service
        if not context.project_root:
            return AgentResult(self.name, "error", {}, "project_root is required for tester")
        result = verification_service.verify(
            context.project_root,
            context.evidence.get("validation_plan", []),
        )
        return AgentResult(self.name, "ok" if result.get("passed") else "failed", result)


class SecurityAgent:
    name = "security"

    async def run(self, context: AgentContext) -> AgentResult:
        from app.security_review import review_security
        result = review_security(context.evidence.get("changes", []))
        return AgentResult(self.name, "ok" if result.get("approved") else "rejected", result)


class ArchitectureAgent:
    name = "architecture"

    async def run(self, context: AgentContext) -> AgentResult:
        from app.workspace_tools import parse_project_manifest, analyze_project_structure
        if not context.project_root:
            return AgentResult(self.name, "error", {}, "project_root is required for architecture")
        try:
            manifest = parse_project_manifest(context.project_root)
            structure = analyze_project_structure(context.project_root)
            return AgentResult(self.name, "ok", {
                "manifest": manifest,
                "structure": structure[:20000],
                "note": "Deterministic architecture profile; use /architecture for full LLM map.",
            })
        except Exception as exc:
            return AgentResult(self.name, "error", {}, str(exc))




class ImprovementAgent:
    name = "improvement"

    async def run(self, context: AgentContext) -> AgentResult:
        from app.improvement_brain import generate_improvement_candidates
        snapshot = context.evidence.get("health_snapshot") or {}
        cycle_id = context.evidence.get("cycle_id")
        candidates = generate_improvement_candidates(snapshot, cycle_id=cycle_id)
        return AgentResult(self.name, "ok", {
            "candidates": candidates,
            "health_score": snapshot.get("health_score"),
            "note": "Deterministic candidate generation from measured project-health findings.",
        })


class ResearchAgent:
    name = "research"

    async def run(self, context: AgentContext) -> AgentResult:
        from app.web_search import search_web
        result = await search_web(context.task, max_results=8, summarize=False)
        return AgentResult(self.name, "ok" if result.get("status") == "ok" else "error", result, result.get("message", ""))


agent_registry = AgentRegistry()
for _agent in (ContextAgent(), PlannerAgent(), CoderAgent(), DebuggerAgent(), TesterAgent(), ReviewerAgent(), SecurityAgent(), ArchitectureAgent(), ImprovementAgent(), ResearchAgent()):
    agent_registry.register(_agent)
