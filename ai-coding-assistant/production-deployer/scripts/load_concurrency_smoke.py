#!/usr/bin/env python3
"""Non-destructive local concurrency smoke test for the deployer SQLite store."""
from __future__ import annotations
import concurrent.futures
import uuid
from app.store import create_deployment, init_db, list_deployments

init_db()

def create_one(i: int):
    suffix=str(uuid.uuid4())
    package={"id":f"pkg-{suffix}","case_id":f"case-{suffix}","payload":{"case_id":f"case-{suffix}","release_id":f"rel-{suffix}","project_name":"load-smoke","commit_sha":suffix[:8]}}
    auth={"id":f"auth-{suffix}","payload":{"authorization_id":f"auth-{suffix}"}}
    return create_deployment(package=package,authorization=auth,target={"environment":"production","target_id":f"smoke-{i}"},provider="external",strategy="canary",created_by="load-smoke")["id"]

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    ids=list(pool.map(create_one,range(32)))
print({"created":len(ids),"stored":len(list_deployments(project_name="load-smoke",limit=100)),"unique":len(set(ids))})
