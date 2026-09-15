import json
import logging
import re
from typing import TypedDict, Dict, Any, List, Optional
from langgraph.graph import StateGraph, END

from app.config import settings
from app.model_manager import model_manager

logger = logging.getLogger(__name__)

class PlannerState(TypedDict):
    user_request: str
    raw_response: str
    plan_json: Optional[Dict[str, Any]]
    error: Optional[str]
    retry_count: int

def build_planner_prompt(user_request: str) -> str:
    return f"""You are an expert AI software architect and planner.
Your goal is to break down the following large user request into safe, incremental implementation phases.
Do NOT output JSON. Output a simple Markdown document with a list of phases.

Format your response exactly like this:
Goal: [Brief goal]
Summary: [Brief summary]

# Phase 1: [Title]
Description: [What to do]

# Phase 2: [Title]
Description: [What to do]

Rules:
- Break large work into small safe phases (max {settings.MAX_PLAN_PHASES}).
- Each phase must have one clear goal.
- Output ONLY plain text markdown. Do NOT use code blocks or JSON.

USER REQUEST:
{user_request}
"""

def extract_json(raw_text: str) -> str:
    """Parse the markdown and convert it to the expected JSON structure."""
    lines = raw_text.split("\n")
    
    plan = {
        "goal": "Parsed Goal",
        "summary": "Parsed Summary",
        "recommended_stack": [],
        "phases": [],
        "risks": [],
        "next_phase_prompt": "Begin Phase 1"
    }
    
    current_phase = None
    phase_id = 1
    
    for line in lines:
        line = line.strip()
        if line.startswith("Goal:"):
            plan["goal"] = line.replace("Goal:", "").strip()
        elif line.startswith("Summary:"):
            plan["summary"] = line.replace("Summary:", "").strip()
        elif line.startswith("# Phase"):
            if current_phase:
                plan["phases"].append(current_phase)
            
            title = line.split(":", 1)[-1].strip() if ":" in line else line.replace("# Phase", "").strip()
            current_phase = {
                "id": phase_id,
                "title": title,
                "description": "",
                "files_likely_needed": [],
                "dependencies": [phase_id - 1] if phase_id > 1 else [],
                "success_criteria": ["Phase completed"],
                "allowed_actions": ["create_file", "modify_file", "read_file"],
                "forbidden_actions": ["delete_unrelated_files"]
            }
            phase_id += 1
        elif line.startswith("Description:") and current_phase:
            current_phase["description"] = line.replace("Description:", "").strip()
            
    if current_phase:
        plan["phases"].append(current_phase)
        
    if not plan["phases"]:
        # Fallback if parsing completely fails
        plan["phases"] = [{
            "id": 1,
            "title": "Initial Draft",
            "description": "Implement the requested features.",
            "files_likely_needed": [],
            "dependencies": [],
            "success_criteria": ["Code written"],
            "allowed_actions": ["create_file", "modify_file", "read_file"],
            "forbidden_actions": ["delete_unrelated_files"]
        }]
        
    return json.dumps(plan)

def build_fallback_plan(user_request: str) -> Dict[str, Any]:
    """Safe fallback plan if LLM fails repeatedly."""
    return {
        "goal": f"Fallback implementation for: {user_request[:50]}...",
        "summary": "A safe incremental plan generated automatically as a fallback.",
        "recommended_stack": [],
        "phases": [
            {
                "id": 1,
                "title": "Initial Analysis",
                "description": "Analyze the codebase for necessary changes.",
                "files_likely_needed": [],
                "dependencies": [],
                "success_criteria": ["Analysis complete"],
                "allowed_actions": ["read_file"],
                "forbidden_actions": ["modify_file", "delete_unrelated_files"]
            },
            {
                "id": 2,
                "title": "Implementation Draft",
                "description": "Draft the requested features incrementally.",
                "files_likely_needed": [],
                "dependencies": [1],
                "success_criteria": ["Code implemented"],
                "allowed_actions": ["create_file", "modify_file", "read_file"],
                "forbidden_actions": ["delete_unrelated_files", "remove_existing_features"]
            }
        ],
        "risks": ["Fallback plan may be too generic"],
        "next_phase_prompt": "Begin Phase 1: Analyze the codebase."
    }

async def planner_node(state: PlannerState) -> PlannerState:
    """Query the LLM to generate the JSON plan."""
    logger.info(f"Running planner node (retry {state['retry_count']})")
    
    prompt = build_planner_prompt(state["user_request"])
    
    try:
        response = await model_manager.generate_completion(
            prompt=prompt,
            model=settings.PLANNER_MODEL,
            temperature=0.2,
            max_tokens=3000,
            system_prompt="You are a strict JSON-only architectural planner."
        )
        state["raw_response"] = response
        state["error"] = None
    except Exception as e:
        logger.error(f"Planner LLM failed: {e}")
        state["error"] = str(e)
        state["raw_response"] = ""
        
    return state

def validate_json_node(state: PlannerState) -> PlannerState:
    """Validate and parse the JSON plan."""
    if state["error"]:
        # If the LLM call failed entirely, increment retry or fallback
        state["retry_count"] += 1
        return state
        
    raw_text = state["raw_response"]
    json_str = extract_json(raw_text)
    
    try:
        data = json.loads(json_str)
        
        # Check required keys
        required_keys = ["goal", "summary", "phases", "next_phase_prompt"]
        missing = [k for k in required_keys if k not in data]
        if missing:
            raise ValueError(f"Missing required keys: {missing}")
            
        if not isinstance(data.get("phases"), list) or len(data["phases"]) == 0:
            raise ValueError("Phases must be a non-empty list.")
            
        state["plan_json"] = data
        state["error"] = None
        
    except Exception as e:
        logger.error(f"Failed to parse plan JSON: {e}")
        state["error"] = f"JSON parse error: {str(e)}"
        state["retry_count"] += 1
        
    return state

def routing_logic(state: PlannerState) -> str:
    """Determine whether to end, retry, or fallback."""
    if state["plan_json"] is not None:
        return "success"
    if state["retry_count"] >= 2:
        return "fallback"
    return "retry"

def fallback_node(state: PlannerState) -> PlannerState:
    """Apply the fallback safe plan."""
    logger.warning("Applying fallback plan due to repeated failures.")
    state["plan_json"] = build_fallback_plan(state["user_request"])
    state["error"] = "Used fallback due to parsing/LLM errors."
    return state

# Build Graph
builder = StateGraph(PlannerState)
builder.add_node("planner", planner_node)
builder.add_node("validator", validate_json_node)
builder.add_node("fallback", fallback_node)

builder.set_entry_point("planner")
builder.add_edge("planner", "validator")

builder.add_conditional_edges(
    "validator",
    routing_logic,
    {
        "success": END,
        "retry": "planner",
        "fallback": "fallback"
    }
)
builder.add_edge("fallback", END)

planner_graph = builder.compile()

async def create_plan(user_request: str) -> Dict[str, Any]:
    """Internal API hook for creating a plan autonomously."""
    initial_state = PlannerState(
        user_request=user_request,
        raw_response="",
        plan_json=None,
        error=None,
        retry_count=0
    )
    
    final_state = await planner_graph.ainvoke(initial_state)
    
    if final_state.get("plan_json"):
        # Add fallback flag if applicable
        if final_state.get("error") and "fallback" in final_state["error"].lower():
            final_state["plan_json"]["fallback_used"] = True
        return final_state["plan_json"]
        
    # Absolute worst case fallback if graph completely blows up
    fallback = build_fallback_plan(user_request)
    fallback["fallback_used"] = True
    return fallback
