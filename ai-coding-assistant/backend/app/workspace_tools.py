import os
import subprocess
import json
from pathlib import Path
from app.config import settings

def _resolve_safe_path(requested_path: str) -> Path:
    """Resolve a path and ensure it falls within the WORKSPACE_ROOT."""
    base_dir = Path(settings.WORKSPACE_ROOT).resolve()
    
    if os.path.isabs(requested_path):
        target = Path(requested_path).resolve()
    else:
        target = (base_dir / requested_path).resolve()
        
    try:
        target.relative_to(base_dir)
        return target
    except ValueError:
        raise ValueError(f"Path '{requested_path}' is outside the allowed workspace boundary: {base_dir}")

def execute_command(command: str) -> str:
    """Execute a shell command inside the workspace root.

    Uses shlex.split to tokenize the command string into a safe argument list,
    then runs with shell=False to eliminate shell injection risk.
    Note: shlex.split uses POSIX mode=False on Windows to handle backslash paths correctly.
    """
    import shlex, sys
    try:
        # posix=False on Windows so backslash path separators are preserved correctly
        args = shlex.split(command, posix=(sys.platform != "win32"))
        result = subprocess.run(
            args,
            shell=False,
            cwd=settings.WORKSPACE_ROOT,
            capture_output=True,
            text=True,
            timeout=120
        )

        output = result.stdout
        if result.stderr:
            output += f"\n[STDERR]:\n{result.stderr}"

        if result.returncode != 0:
            return f"Command failed with exit code {result.returncode}.\nOutput:\n{output}"

        return output if output else "Command executed successfully with no output."
    except subprocess.TimeoutExpired:
        return "Command timed out after 120 seconds."
    except Exception as e:
        return f"Error executing command: {str(e)}"


def list_directory(path: str) -> str:
    """List contents of a directory in the workspace."""
    try:
        target = _resolve_safe_path(path)
        if not target.exists():
            return f"Error: Directory '{path}' does not exist."
        if not target.is_dir():
            return f"Error: '{path}' is not a directory."
            
        items = os.listdir(target)
        output = [f"Contents of {path}:"]
        for item in sorted(items):
            item_path = target / item
            is_dir = item_path.is_dir()
            prefix = "[DIR] " if is_dir else "[FILE]"
            output.append(f"{prefix} {item}")
        return "\n".join(output)
    except Exception as e:
        return f"Error reading directory: {str(e)}"

def write_file(path: str, content: str) -> str:
    """Write content to a file in the workspace."""
    try:
        target = _resolve_safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        
        with open(target, 'w', encoding='utf-8') as f:
            f.write(content)
            
        return f"Successfully wrote to {target}"
    except Exception as e:
        return f"Error writing file: {str(e)}"

def read_file(path: str) -> str:
    """Read content from a file in the workspace."""
    try:
        target = _resolve_safe_path(path)
        if not target.is_file():
            return f"Error: '{target}' is not a file or does not exist."
            
        with open(target, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

def analyze_project_structure(path: str = ".") -> str:
    """Recursively analyze a project directory, returning a tree structure and key files to give the LLM context."""
    try:
        target = _resolve_safe_path(path)
        if not target.is_dir():
            return f"Error: '{target}' is not a directory or does not exist."
            
        tree = []
        for root, dirs, files in os.walk(target):
            # Ignore common heavy directories
            dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', 'venv', '__pycache__', 'dist', 'build']]
            level = root.replace(str(target), '').count(os.sep)
            indent = ' ' * 4 * (level)
            tree.append(f"{indent}{os.path.basename(root)}/")
            subindent = ' ' * 4 * (level + 1)
            for f in files:
                tree.append(f"{subindent}{f}")
                
        # Limit output length to prevent context explosion on 4GB VRAM
        output = "\n".join(tree)
        if len(output) > 5000:
            return output[:5000] + "\n... [TRUNCATED - Directory too large]"
        return output
    except Exception as e:
        return f"Error analyzing project structure: {str(e)}"


def parse_project_manifest(project_path: str) -> dict:
    """
    Parse project manifest files (requirements.txt, package.json, pyproject.toml,
    docker-compose.yml) without any LLM calls to produce a deterministic project profile.

    Also scans the parent directory for sibling service directories (e.g. frontend
    sitting next to backend) so the caller knows the full multi-service layout.
    """
    import re

    base = Path(project_path).resolve()
    profile = {
        "project_path": str(base),
        "language": "unknown",
        "framework": "unknown",
        "test_runner": "unknown",
        "install_cmd": "",
        "start_cmd": "",
        "port": None,
        "python_version": "3.11",
        "node_version": "18",
        "dependency_file": "",
        "services": [],          # all detected services incl. siblings
        "has_frontend": False,
        "has_backend": False,
        "has_docker": False,
        "has_cicd": False,
        "has_tests": False,
        "has_readme": False,
        "has_env_example": False,
        "raw_dependencies": [],
    }

    # ── Helper: detect Python project ────────────────────────────────────────
    def _parse_python(directory: Path, svc: dict):
        deps = []
        req_file = directory / "requirements.txt"
        pyproject = directory / "pyproject.toml"

        if req_file.exists():
            svc["dependency_file"] = "requirements.txt"
            svc["install_cmd"] = "pip install -r requirements.txt"
            try:
                lines = req_file.read_text(encoding="utf-8").lower().splitlines()
                deps = [l.split("==")[0].split(">=")[0].strip() for l in lines if l.strip() and not l.startswith("#")]
            except Exception:
                pass
        elif pyproject.exists():
            svc["dependency_file"] = "pyproject.toml"
            svc["install_cmd"] = "pip install ."

        svc["language"] = "python"
        svc["raw_dependencies"] = deps

        # Framework detection
        if any("django" in d for d in deps):
            svc["framework"] = "django"
            svc["start_cmd"] = "python manage.py runserver 0.0.0.0:8000"
            svc["port"] = 8000
        elif any("fastapi" in d for d in deps):
            svc["framework"] = "fastapi"
            svc["start_cmd"] = "uvicorn app.main:app --host 0.0.0.0 --port 8000"
            svc["port"] = 8000
        elif any("flask" in d for d in deps):
            svc["framework"] = "flask"
            svc["start_cmd"] = "flask run --host=0.0.0.0"
            svc["port"] = 5000

        # Test runner
        if any("pytest" in d for d in deps):
            svc["test_runner"] = "pytest"
        else:
            svc["test_runner"] = "python -m unittest"

        # Python version from .python-version or runtime.txt
        for vf in [".python-version", "runtime.txt"]:
            vp = directory / vf
            if vp.exists():
                try:
                    ver = vp.read_text().strip().replace("python-", "").replace("python", "").strip()
                    if re.match(r"\d+\.\d+", ver):
                        svc["python_version"] = ver
                        break
                except Exception:
                    pass

        # Base image for Dockerfile
        svc["base_image"] = f"python:{svc.get('python_version', '3.11')}-slim"

    # ── Helper: detect Node.js project ───────────────────────────────────────
    def _parse_node(directory: Path, svc: dict):
        pkg = directory / "package.json"
        try:
            import json as _json
            data = _json.loads(pkg.read_text(encoding="utf-8"))
        except Exception:
            return

        svc["language"] = "javascript"
        svc["dependency_file"] = "package.json"
        svc["install_cmd"] = "npm install"
        svc["raw_dependencies"] = list(data.get("dependencies", {}).keys()) + list(data.get("devDependencies", {}).keys())

        deps_lower = [d.lower() for d in svc["raw_dependencies"]]

        # Framework detection
        if "react" in deps_lower or "react-dom" in deps_lower:
            svc["framework"] = "react"
            svc["has_frontend"] = True
        elif "vue" in deps_lower:
            svc["framework"] = "vue"
            svc["has_frontend"] = True
        elif "next" in deps_lower:
            svc["framework"] = "nextjs"
            svc["has_frontend"] = True
        elif "express" in deps_lower:
            svc["framework"] = "express"

        # Scripts
        scripts = data.get("scripts", {})
        svc["start_cmd"] = scripts.get("start", "npm start")
        svc["test_runner"] = "npm test" if "test" in scripts else "jest"

        # Port
        start_script = scripts.get("start", "")
        port_match = re.search(r"PORT[=\s]+(\d{4,5})", start_script)
        svc["port"] = int(port_match.group(1)) if port_match else 3000

        # Node version from .nvmrc or .node-version
        for vf in [".nvmrc", ".node-version"]:
            vp = directory / vf
            if vp.exists():
                try:
                    ver = vp.read_text().strip().lstrip("v")
                    if re.match(r"\d+", ver):
                        svc["node_version"] = ver.split(".")[0]
                        break
                except Exception:
                    pass

        svc["base_image"] = f"node:{svc.get('node_version', '18')}-alpine"

    # ── Analyse a single directory and return a service dict ─────────────────
    def _analyse_service(directory: Path, name: str) -> dict:
        svc = {
            "name": name,
            "path": str(directory),
            "language": "unknown",
            "framework": "unknown",
            "test_runner": "unknown",
            "install_cmd": "",
            "start_cmd": "",
            "port": None,
            "dependency_file": "",
            "base_image": "ubuntu:22.04",
            "raw_dependencies": [],
            "has_frontend": False,
            "python_version": "3.11",
            "node_version": "18",
        }

        if (directory / "requirements.txt").exists() or (directory / "pyproject.toml").exists():
            _parse_python(directory, svc)
            svc["has_backend"] = True
        elif (directory / "package.json").exists():
            _parse_node(directory, svc)
        return svc

    # ── Scan the given project directory ─────────────────────────────────────
    primary_svc = _analyse_service(base, base.name)
    profile.update({
        "language": primary_svc["language"],
        "framework": primary_svc["framework"],
        "test_runner": primary_svc["test_runner"],
        "install_cmd": primary_svc["install_cmd"],
        "start_cmd": primary_svc["start_cmd"],
        "port": primary_svc["port"],
        "dependency_file": primary_svc["dependency_file"],
        "base_image": primary_svc.get("base_image", "ubuntu:22.04"),
        "python_version": primary_svc["python_version"],
        "node_version": primary_svc["node_version"],
        "raw_dependencies": primary_svc["raw_dependencies"],
    })
    profile["services"].append(primary_svc)

    # ── Scan siblings for multi-service detection (frontend next to backend) ──
    parent = base.parent
    IGNORE = {"node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build", "data", "backups"}
    try:
        for sibling in sorted(parent.iterdir()):
            if sibling == base or not sibling.is_dir() or sibling.name in IGNORE:
                continue
            # Only count as a service if it has a manifest
            has_py = (sibling / "requirements.txt").exists() or (sibling / "pyproject.toml").exists()
            has_node = (sibling / "package.json").exists()
            if has_py or has_node:
                sibling_svc = _analyse_service(sibling, sibling.name)
                profile["services"].append(sibling_svc)
                if sibling_svc.get("has_frontend") or sibling_svc.get("framework") in ("react", "vue", "nextjs"):
                    profile["has_frontend"] = True
    except Exception:
        pass

    profile["has_backend"] = any(
        s.get("language") == "python" or s.get("framework") in ("django", "fastapi", "flask", "express")
        for s in profile["services"]
    )

    # ── Check for existing DevOps files ──────────────────────────────────────
    # Check both project dir and parent (monorepo root)
    check_dirs = [base, parent]
    for d in check_dirs:
        if (d / "Dockerfile").exists() or (d / "docker-compose.yml").exists():
            profile["has_docker"] = True
        if (d / ".github" / "workflows").exists() or (d / ".gitlab-ci.yml").exists() or (d / "Jenkinsfile").exists():
            profile["has_cicd"] = True
        if (d / "README.md").exists() or (d / "readme.md").exists():
            profile["has_readme"] = True
        if (d / ".env.example").exists() or (d / ".env.sample").exists():
            profile["has_env_example"] = True

    # Check for tests dir
    for d in [base] + [Path(s["path"]) for s in profile["services"]]:
        if (d / "tests").exists() or (d / "test").exists() or list(d.glob("test_*.py")) or list(d.glob("*.test.js")):
            profile["has_tests"] = True
            break

    return profile



# Schema definitions for LLMs
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "Execute a bash shell command within the workspace root. Use this to install dependencies, run tests, initialize projects, or run simple scripts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file at the specified path with the provided content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The relative path to the file (e.g. 'src/index.js'). NEVER use absolute paths starting with '/'."
                    },
                    "content": {
                        "type": "string",
                        "description": "The full content to write to the file."
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the text contents of a specified file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The relative path to the file. NEVER use absolute paths starting with '/'."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the files and folders inside a specified directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The relative path to the directory (use '.' for root)."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_project_structure",
            "description": "Recursively analyze a project directory to understand the entire workspace architecture. Automatically ignores heavy directories like node_modules.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The relative path to the directory (use '.' for root)."
                    }
                },
                "required": ["path"]
            }
        }
    }
]

# Dispatcher mapping
AVAILABLE_TOOLS = {
    "execute_command": execute_command,
    "write_file": write_file,
    "read_file": read_file,
    "list_directory": list_directory,
    "analyze_project_structure": analyze_project_structure
}
