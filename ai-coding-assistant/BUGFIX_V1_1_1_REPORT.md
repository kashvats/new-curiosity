# AI Coding Assistant v1.1.1 Bug-Fix Audit

This patch release is a second-pass bug hunt over v1.1.0. It intentionally adds no new trust boundary or production authority.

## Bugs found and fixed

1. **Ollama 404 fallback deadlock** — completion, tool-chat, and streaming fallback recursively reacquired a one-slot semaphore while the original call still held it. Fallback now releases the semaphore between attempts and rejects a fallback equal to the missing model.
2. **Cross-event-loop Ollama semaphore reuse** — the global semaphore could be reused across separate asyncio loops during reloads/tests. It is now recreated per running loop.
3. **Filesystem watcher callbacks were ineffective** — watchdog callbacks execute on a worker thread, where `asyncio.get_running_loop()` fails. The watcher now captures the application loop and marshals events back with `call_soon_threadsafe`.
4. **File modifications were ignored** — `on_modified` was a no-op. Modified, created, deleted, and moved files now trigger the debounced architecture refresh path.
5. **Watcher restartability** — a stopped `PollingObserver` cannot be started again. A fresh observer is created per application lifespan and shutdown is bounded.
6. **Python relative-import graph ambiguity** — `from .shared import X` lost its relative-import level and could connect to another package's `shared.py`. Relative imports are now package-aware in repository intelligence and local IDE neighbor discovery.
7. **Experience-memory recency tie ordering** — equally relevant experiences could return older evidence before newer evidence. Ties now prefer the most recently observed experience.
8. **Experience-memory concurrent insert race** — SELECT-then-INSERT could lose/raise on identical experiences recorded concurrently. Recording now uses an atomic SQLite UPSERT and occurrence counts remain correct.
9. **Security routing vocabulary gap** — tasks such as `Fix authentication bypass` could be routed as ordinary targeted work. Authentication/credential/bypass variants now enter the security route, and bypasses request an initial diagnosis.
10. **Malformed benchmark metric handling** — non-numeric benchmark fields could raise an uncaught `TypeError` and become a 500. They now raise a controlled validation `ValueError`/HTTP 400 path.
11. **Pre-approval live repository writes** — the orchestrator wrote `raw_prompt.md` and `plan.md` directly into the selected source tree before human approval. Planning artifacts are now kept in returned orchestration state; live source remains untouched until the existing explicit apply path.

## Regression coverage

`backend/tests/test_v11_bugfixes.py` covers the fixes above, including semaphore fallback timeouts, watcher thread marshalling, relative-import ambiguity, concurrent experience writes, security routing, malformed benchmark input, and the no-live-write orchestration invariant.

## Safety boundary

No production-deployment authority was added to the AI backend. The independent production deployer, governance, staging, certification, and signed-outcome learning boundaries remain unchanged.
