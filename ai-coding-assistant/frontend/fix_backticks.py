import os
import re

root = r'c:\Users\human-bot\projects\new-curiosity\ai-coding-assistant\frontend\src\features'

modified = 0
for dirpath, _, filenames in os.walk(root):
    for filename in filenames:
        if filename.endswith('.jsx'):
            filepath = os.path.join(dirpath, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find broken template literals missing closing backtick and comma
            # For example: width: `${pct}%
            # Replace it with width: `${pct}%`,
            new_content = re.sub(r'width:\s*`\$\{([^\}]+)\}%[^\n`]*\n', r'width: `${{\1}}%`,\n', content)
            
            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                modified += 1

print(f'Fixed missing backticks in {modified} files.')
