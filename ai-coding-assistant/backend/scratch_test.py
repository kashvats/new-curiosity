import asyncio
import sys
import os

# Ensure app can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def main():
    from app.planner import create_plan
    
    print("Testing internal LangGraph planner node...")
    
    request = "Build a simple user authentication module with login and registration."
    print(f"User Request: {request}")
    
    try:
        plan = await create_plan(request)
        print("\n--- GENERATED PLAN ---")
        import json
        print(json.dumps(plan, indent=2))
        print("----------------------")
        print("Success! Planner node executed autonomously without API endpoints.")
    except Exception as e:
        print(f"Error during planning: {e}")

if __name__ == "__main__":
    asyncio.run(main())
