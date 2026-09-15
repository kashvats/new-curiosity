"""Offline smoke report for v1.1 routing and repository intelligence."""
from __future__ import annotations
import argparse
import json
from app.adaptive_orchestration import route_task
from app.project_paths import resolve_project_root
from app.repository_intelligence import rank_relevant_files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_name")
    parser.add_argument("task")
    parser.add_argument("--file", action="append", default=[])
    args = parser.parse_args()
    route = route_task(args.task, files=args.file)
    root = resolve_project_root(args.project_name)
    context = rank_relevant_files(root, args.task, seed_files=args.file, limit=route.context_file_budget)
    print(json.dumps({"route": route.to_dict(), "repository_context": context}, indent=2))


if __name__ == "__main__":
    main()
