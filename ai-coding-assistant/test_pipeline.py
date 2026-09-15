import requests
import time
import json
import sys

BASE_URL = "http://localhost:8000"
PROJECT = "ai_tutor"

print(f"--- 1. Triggering Audit for {PROJECT} ---")
try:
    resp = requests.post(f"{BASE_URL}/projects/audit/run", json={"project_name": PROJECT}, timeout=300)
    resp.raise_for_status()
    audit_data = resp.json()
    print("Audit Response:", json.dumps(audit_data, indent=2)[:500], "...\n")
except Exception as e:
    print(f"Failed to run audit: {e}")
    sys.exit(1)

fix_queue = audit_data.get("fix_queue", [])
if not fix_queue:
    print("No fix queue generated.")
    sys.exit(0)

# 2. Pick the first fix task
target_task = fix_queue[0]
print(f"--- 2. Triggering Fix for Task: {target_task.get('task', 'Unknown')} ---")

req_payload = {
    "project_name": PROJECT,
    "task": target_task["task"],
    "changes": {}
}

try:
    print("Sending fix request (this may take a few minutes)...")
    fix_resp = requests.post(f"{BASE_URL}/projects/audit/fix/apply", json=req_payload, timeout=600)
    fix_resp.raise_for_status()
    fix_data = fix_resp.json()
    print("\nFix Response:", json.dumps(fix_data, indent=2))
except Exception as e:
    print(f"Failed to run fix apply: {e}")
    sys.exit(1)

# 3. List sessions to see if it was tracked properly
print("\n--- 3. Checking Session History ---")
try:
    sess_resp = requests.get(f"{BASE_URL}/projects/audit/fix/sessions?project_name={PROJECT}")
    sess_resp.raise_for_status()
    print("Sessions:", json.dumps(sess_resp.json(), indent=2))
except Exception as e:
    print(f"Failed to get sessions: {e}")
