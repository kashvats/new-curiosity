import json
import httpx
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.config import settings
from app.model_manager import get_effective_model
from app.project_rules import get_enabled_rules_text

def read_relevant_files_for_tests(file_paths: List[str]) -> List[Dict[str, str]]:
    root = Path(settings.workspace_root).resolve()
    read_files = []
    
    paths_to_read = file_paths[:settings.max_code_context_files]
    
    for rel_path in paths_to_read:
        try:
            target = (root / rel_path).resolve()
            if root not in target.parents and target != root:
                read_files.append({"path": rel_path, "content": "<Error: Path traversal blocked>"})
                continue
                
            if not target.exists():
                read_files.append({"path": rel_path, "content": "<Error: File does not exist>"})
                continue
                
            if not target.is_file():
                read_files.append({"path": rel_path, "content": "<Error: Not a file>"})
                continue
                
            content = target.read_text(encoding="utf-8")
            
            if len(content) > settings.max_code_file_chars:
                half = settings.max_code_file_chars // 2
                content = content[:half] + f"\n\n...<TRUNCATED: File exceeded {settings.max_code_file_chars} chars>...\n\n" + content[-half:]
                
            read_files.append({"path": rel_path, "content": content})
        except Exception as e:
            read_files.append({"path": rel_path, "content": f"<Error reading file: {str(e)}>"})
            
    return read_files

def build_test_generation_prompt(task: str, files: List[Dict[str, str]], impact_report: dict = None, extra_context: str = None) -> str:
    rules_text = get_enabled_rules_text(["general", "testing", "safety", "agents"])
    
    prompt = f"You are an expert Software Test Engineer specializing in generating robust, maintainable tests.\n\n{rules_text}\n\n"
    
    if impact_report:
        prompt += f"IMPACT ANALYSIS REPORT:\n"
        prompt += f"Risk Level: {impact_report['risk_level']}\n"
        prompt += f"Impacted Files: {', '.join(impact_report['impacted_files'])}\n"
        prompt += f"Impacted Tests: {', '.join(impact_report['impacted_tests'])}\n"
        prompt += f"Recommendations: {', '.join(impact_report['recommendations'])}\n\n"
        prompt += "CRITICAL IMPACT RULES:\n"
        prompt += "- Focus your tests on mitigating the risks identified above.\n"
        prompt += "- Mention any completely untested high-risk areas in your warnings.\n\n"
        
    prompt += """Only work on generating tests. Do not modify source code files.
Prefer writing test files directly. If no test framework exists, propose minimal setup but do not install packages automatically.
Use existing project testing style if detected.
Avoid fragile tests that depend on exact strings unless necessary.

Return strict JSON ONLY. Do not write markdown blocks around the JSON.
Your response must be parseable by json.loads().

EXPECTED JSON FORMAT:
{
  "summary": "string",
  "test_strategy": "string detailing what tests were written and why",
  "files_read": ["path"],
  "proposed_changes": [
    {
      "path": "relative/path/to/test_file.py",
      "action": "create|modify|patch",
      "reason": "why this test file needs change",
      "content": "complete file content (required for create/modify)",
      "patch": "unified diff patch text (required for patch)"
    }
  ],
  "commands_to_run_manually": ["string"],
  "warnings": ["string"]
}

Important Rules:
- "proposed_changes" must specify "action". Allowed values: create, modify, patch.
- You MUST only create/modify files that are test files (e.g. starting with `test_`, ending with `.test.js`, located in `tests/`, etc.).
- Do NOT delete files. Do NOT rename files. Do NOT execute commands.
- For "create" or "modify", provide full "content".
- For "patch", provide the standard unified diff.
"""

    if extra_context:
        prompt += f"\nEXTRA CONTEXT:\n{extra_context}\n"
        
    if files:
        prompt += "\nEXISTING FILES (Source of Truth):\n"
        for f in files:
            prompt += f"\n--- {f['path']} ---\n{f['content']}\n"
            
    prompt += f"\nTASK:\n{task}\n"
    return prompt

async def call_test_generator_model(prompt: str) -> str:
    url = f"{settings.ollama_base_url}/api/generate"
    model_name = get_effective_model("coder") # using coder role for test gen, fallback handled by config
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json().get("response", "")

def extract_test_changes_json(raw_text: str) -> dict:
    json_str = raw_text
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', raw_text, re.DOTALL)
    if match:
        json_str = match.group(1)
        
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {str(e)}\nRaw was: {raw_text[:200]}")

def is_test_file_path(path: str) -> bool:
    p = path.lower()
    if p.startswith("test_") or "tests/" in p or "__tests__" in p or "e2e/" in p:
        return True
    if p.endswith(".test.js") or p.endswith(".spec.js") or p.endswith(".test.ts") or p.endswith(".spec.ts"):
        return True
    if p.endswith(".test.jsx") or p.endswith(".spec.jsx") or p.endswith(".test.tsx") or p.endswith(".spec.tsx"):
        return True
    if p.endswith("_test.py"):
        return True
    return False

async def generate_test_changes(task: str, file_paths: List[str], impact_report_id: str = None, extra_context: str = None) -> dict:
    impact_report = None
    if impact_report_id:
        try:
            from app.impact_analysis import get_impact_report
            impact_report = get_impact_report(impact_report_id)
            if impact_report:
                for f in impact_report["impacted_files"]:
                    if f not in file_paths:
                        file_paths.append(f)
        except ImportError:
            pass

    files_data = read_relevant_files_for_tests(file_paths)
    prompt = build_test_generation_prompt(task, files_data, impact_report, extra_context)
    model_name = get_effective_model("coder")
    
    try:
        raw_response = await call_test_generator_model(prompt)
        parsed = extract_test_changes_json(raw_response)
        
        # Safety validation
        valid_changes = []
        warnings = parsed.get("warnings", [])
        for c in parsed.get("proposed_changes", []):
            action = c.get("action")
            path = c.get("path", "")
            if action not in ["create", "modify", "patch"]:
                warnings.append(f"Rejected action '{action}' on {path}. Only create, modify, or patch allowed.")
                continue
            
            if ".." in path or path.startswith("/"):
                warnings.append(f"Rejected suspicious path {path}.")
                continue
                
            if not is_test_file_path(path):
                # The agent tried to modify a source file
                warnings.append(f"Rejected proposed change to '{path}'. Test Generator is only allowed to modify test files.")
                continue
                
            content = c.get("content")
            patch = c.get("patch")
            if action in ["create", "modify"] and not content:
                warnings.append(f"Rejected {action} on {path} due to missing content.")
                continue
                
            if action == "patch" and not patch:
                warnings.append(f"Rejected patch on {path} due to missing patch content.")
                continue
                
            valid_changes.append(c)
            
        parsed["proposed_changes"] = valid_changes
        parsed["warnings"] = warnings
        
        return {
            "status": "ok",
            "model": model_name,
            "result": parsed
        }
    except Exception as e:
        return {
            "status": "error",
            "model": model_name,
            "message": str(e)
        }


router = APIRouter(prefix="/tests/generate", tags=["test_generator"])

class TestGenerationRequest(BaseModel):
    task: str
    file_paths: List[str] = Field(default_factory=list)
    impact_report_id: Optional[str] = None
    extra_context: Optional[str] = None

@router.post("")
async def generate_tests_endpoint(req: TestGenerationRequest):
    result = await generate_test_changes(
        req.task, list(req.file_paths), req.impact_report_id, req.extra_context
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message", "Test generation failed"))
    return result
