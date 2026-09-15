"""
Project-specific rules and conventions management.
"""
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ProjectRules:
    """Manage project-specific rules and conventions."""
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.rules = self._load_rules()
    
    def _load_rules(self) -> Dict[str, Any]:
        """Load rules from project configuration."""
        rules = {
            "language": self._detect_language(),
            "test_framework": self._detect_test_framework(),
            "linting": self._detect_linting(),
            "formatting": self._detect_formatting()
        }
        return rules
    
    def _detect_language(self) -> str:
        """Detect primary programming language."""
        if (self.project_path / "package.json").exists():
            return "javascript"
        elif (self.project_path / "requirements.txt").exists():
            return "python"
        elif (self.project_path / "pom.xml").exists():
            return "java"
        elif (self.project_path / "go.mod").exists():
            return "go"
        elif (self.project_path / "Cargo.toml").exists():
            return "rust"
        return "unknown"
    
    def _detect_test_framework(self) -> Optional[str]:
        """Detect testing framework."""
        lang = self.rules.get("language") if hasattr(self, "rules") else self._detect_language()
        
        if lang == "python":
            if (self.project_path / "pytest.ini").exists():
                return "pytest"
            return "unittest"
        elif lang == "javascript":
            package_json = self.project_path / "package.json"
            if package_json.exists():
                import json
                data = json.loads(package_json.read_text())
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                if "jest" in deps:
                    return "jest"
                elif "mocha" in deps:
                    return "mocha"
                elif "vitest" in deps:
                    return "vitest"
        
        return None
    
    def _detect_linting(self) -> Optional[str]:
        """Detect linting configuration."""
        if (self.project_path / ".eslintrc").exists():
            return "eslint"
        elif (self.project_path / ".pylintrc").exists():
            return "pylint"
        elif (self.project_path / "ruff.toml").exists():
            return "ruff"
        return None
    
    def _detect_formatting(self) -> Optional[str]:
        """Detect code formatting tool."""
        if (self.project_path / ".prettierrc").exists():
            return "prettier"
        elif (self.project_path / "pyproject.toml").exists():
            return "black"
        return None
    
    def get_test_command(self) -> str:
        """Get the command to run tests."""
        framework = self.rules.get("test_framework")
        lang = self.rules.get("language")
        
        if framework == "pytest":
            return "pytest"
        elif framework == "jest":
            return "npm test"
        elif framework == "vitest":
            return "npm test"
        elif lang == "python":
            return "python -m unittest"
        
        return "echo 'No test framework detected'"
    
    def get_lint_command(self) -> Optional[str]:
        """Get the command to run linting."""
        linter = self.rules.get("linting")
        
        if linter == "eslint":
            return "npm run lint"
        elif linter == "pylint":
            return "pylint ."
        elif linter == "ruff":
            return "ruff check ."
        
        return None

def get_enabled_rules_text(project_path: str = None) -> str:
    """Get a formatted string of enabled rules for a project."""
    if not project_path:
        from app.config import settings
        project_path = settings.WORKSPACE_ROOT
        
    try:
        rules_manager = ProjectRules(project_path)
        rules = rules_manager.rules
        
        lines = ["Enabled Project Rules:"]
        if rules.get("language"):
            lines.append(f"- Language: {rules['language']}")
        if rules.get("test_framework"):
            lines.append(f"- Test Framework: {rules['test_framework']}")
        if rules.get("linting"):
            lines.append(f"- Linting: {rules['linting']}")
        if rules.get("formatting"):
            lines.append(f"- Formatting: {rules['formatting']}")
            
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to get rules text: {e}")
        return "No specific project rules detected."
