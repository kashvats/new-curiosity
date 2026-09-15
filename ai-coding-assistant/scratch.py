import re

def extract_markdown_changes(raw_text: str) -> dict:
    data = {
        "summary": "Generated via Markdown",
        "task_understood": "Yes",
        "files_read": [],
        "proposed_changes": [],
        "commands_to_run_manually": [],
        "warnings": []
    }
    
    summary_match = re.search(r"# Summary\n(.*?)(?=# Changes)", raw_text, re.DOTALL | re.IGNORECASE)
    if summary_match:
        data["summary"] = summary_match.group(1).strip()
        
    changes_blocks = re.split(r"^##\s+\[?([^\]\n]+)\]?", raw_text, flags=re.MULTILINE)
    
    for i in range(1, len(changes_blocks) - 1, 2):
        file_path = changes_blocks[i].strip()
        block_content = changes_blocks[i+1]
        
        action_match = re.search(r"### Action:\s*(create|modify)", block_content, re.IGNORECASE)
        action = action_match.group(1).lower().strip() if action_match else "modify"
        
        content_split = re.split(r"### Content:", block_content, flags=re.IGNORECASE)
        if len(content_split) > 1:
            file_content = content_split[1].strip()
            if file_content.startswith("```"):
                file_content = re.sub(r"^```[a-zA-Z]*\n?", "", file_content)
            if file_content.endswith("```"):
                file_content = file_content[:-3].strip()
                
            data["proposed_changes"].append({
                "path": file_path,
                "action": action,
                "reason": "Parsed from Markdown",
                "content": file_content
            })
            
    return data

target_file = "test.py"
accumulated_code = "print('hello')"
raw_md = f"""# Summary
Iteratively generated code.

# Changes

## {target_file}
### Action: modify
### Content:
```
{accumulated_code.strip()}
```
"""

print(extract_markdown_changes(raw_md))
