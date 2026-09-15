"""
Template rendering for prompts.
"""
from typing import Dict, Any
from jinja2 import Template


def render_template(template_str: str, context: Dict[str, Any]) -> str:
    """Render a Jinja2 template with the given context."""
    template = Template(template_str)
    return template.render(**context)


# Common prompt templates
TEST_GENERATION_PROMPT = """
You are a test generation expert. Generate comprehensive unit tests for the following code.

Code to test:
```
{{ code }}
```

Requirements:
- Use {{ test_framework }} as the testing framework
- Cover edge cases and error handling
- Include positive and negative test cases
- Use descriptive test names

Generate the complete test file.
"""


CODE_REVIEW_PROMPT = """
Review the following code changes and provide feedback.

Changes:
```
{{ changes }}
```

Focus on:
- Code quality and readability
- Potential bugs or issues
- Performance considerations
- Best practices

Provide specific, actionable feedback.
"""


DOCUMENTATION_PROMPT = """
Generate documentation for the following code.

Code:
```
{{ code }}
```

Include:
- Overview of functionality
- Parameter descriptions
- Return value description
- Usage examples
- Any important notes or warnings
"""
