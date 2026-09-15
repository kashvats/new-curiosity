import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from app.config import settings

router = APIRouter(prefix="/tests", tags=["tests"])

TEST_EXCLUDES = {
    "node_modules", ".git", "dist", "build", "__pycache__", ".venv", 
    "data", "backups", "qdrant_storage", "qdrant", ".env", "generated_docs",
    "uploads", "extracted", "screenshots"
}

def is_excluded_path(path_obj: Path, root: Path) -> bool:
    try:
        rel = path_obj.relative_to(root)
        parts = rel.parts
        return any(p in TEST_EXCLUDES for p in parts)
    except ValueError:
        return True

def scan_test_files():
    root = Path(settings.workspace_root).resolve()
    backend_tests = []
    frontend_tests = []
    has_pytest_ini = False
    has_package_json = False
    has_vite_config = False
    
    if not root.exists():
        return backend_tests, frontend_tests, has_pytest_ini, has_package_json, has_vite_config
        
    for filepath in root.rglob("*"):
        if filepath.is_file():
            if is_excluded_path(filepath, root):
                continue
            
            rel_path = filepath.relative_to(root).as_posix()
            filename = filepath.name
            
            # Detect configs
            if filename == "pytest.ini":
                has_pytest_ini = True
            elif filename == "package.json":
                has_package_json = True
            elif filename == "vite.config.js" or filename == "vite.config.ts":
                has_vite_config = True
                
            # Detect backend tests
            if "backend/tests/" in rel_path or filename.startswith("test_") and filename.endswith(".py") or filename.endswith("_test.py"):
                backend_tests.append(rel_path)
                
            # Detect frontend tests
            if filename.endswith(".test.jsx") or filename.endswith(".test.js") or \
               filename.endswith(".spec.jsx") or filename.endswith(".spec.js"):
                frontend_tests.append(rel_path)
                
    return backend_tests, frontend_tests, has_pytest_ini, has_package_json, has_vite_config

def detect_backend_test_commands(backend_tests, has_pytest_ini):
    commands = []
    if backend_tests or has_pytest_ini:
        commands.append({
            "name": "Backend pytest (Local)",
            "command": "cd backend && pytest",
            "reason": "Detected Python backend tests or pytest.ini."
        })
    return commands

def detect_frontend_test_commands(frontend_tests, has_package_json, has_vite_config):
    commands = []
    if frontend_tests:
        if has_vite_config:
            commands.append({
                "name": "Frontend Vitest",
                "command": "cd frontend && npm run test",
                "reason": "Detected frontend test files and vite config (assuming vitest or similar)."
            })
        else:
            commands.append({
                "name": "Frontend Test",
                "command": "cd frontend && npm test",
                "reason": "Detected frontend test files."
            })
    return commands

def detect_docker_test_commands(backend_tests, frontend_tests):
    commands = []
    root = Path(settings.workspace_root).resolve()
    if (root / "docker-compose.yml").exists():
        if backend_tests:
            commands.append({
                "name": "Backend pytest (Docker)",
                "command": "docker compose exec backend pytest",
                "reason": "Detected docker-compose and backend tests."
            })
        if frontend_tests:
            commands.append({
                "name": "Frontend test (Docker)",
                "command": "docker compose exec frontend npm test",
                "reason": "Detected docker-compose and frontend tests."
            })
    return commands

def get_test_plan():
    backend_tests, frontend_tests, has_pytest_ini, has_package_json, has_vite_config = scan_test_files()
    
    suggested_commands = []
    warnings = []
    
    suggested_commands.extend(detect_backend_test_commands(backend_tests, has_pytest_ini))
    suggested_commands.extend(detect_frontend_test_commands(frontend_tests, has_package_json, has_vite_config))
    suggested_commands.extend(detect_docker_test_commands(backend_tests, frontend_tests))
    
    if not backend_tests and not frontend_tests:
        warnings.append("No test files detected in the workspace.")
        
    return {
        "status": "ok",
        "test_files": {
            "backend": backend_tests,
            "frontend": frontend_tests
        },
        "suggested_commands": suggested_commands,
        "warnings": warnings
    }

@router.get("/plan")
async def api_get_test_plan():
    try:
        plan = get_test_plan()
        return plan
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
