"""Optional filesystem watcher for architecture refreshes.

The observer callbacks execute on watchdog's worker thread, so they must marshal
updates onto the FastAPI event loop captured at startup.  The watcher is restartable
across repeated application lifespans/tests.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)
_debouncers: dict[str, asyncio.TimerHandle] = {}

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers.polling import PollingObserver
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    class FileSystemEventHandler:  # type: ignore[no-redef]
        pass
    PollingObserver = None  # type: ignore[assignment]


class ProjectChangeHandler(FileSystemEventHandler):
    def __init__(self, debounce_seconds: int = 10):
        super().__init__()
        self.debounce_seconds = debounce_seconds
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    def on_modified(self, event):
        self._handle_event(event)

    def on_created(self, event):
        self._handle_event(event)

    def on_deleted(self, event):
        self._handle_event(event)

    def on_moved(self, event):
        # Treat both ends of a rename/move as a project change.  For the current
        # architecture refresh, one debounce per project is enough.
        self._handle_event(event)
        dest_path = getattr(event, "dest_path", "")
        if dest_path:
            class _DestEvent:
                is_directory = getattr(event, "is_directory", False)
                src_path = dest_path
            self._handle_event(_DestEvent())

    def _handle_event(self, event):
        if getattr(event, "is_directory", False):
            return
        path = getattr(event, "src_path", "")
        if not path or any(ignore in path for ignore in [".git", "node_modules", "venv", "__pycache__", ".venv"]):
            return
        try:
            rel_path = os.path.relpath(path, settings.WORKSPACE_ROOT)
        except (TypeError, ValueError):
            return
        parts = rel_path.split(os.sep)
        if len(parts) < 2 or parts[0] in {"..", "."}:
            return
        project_name = parts[0]
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._debounce_project_update, project_name)
        except RuntimeError:
            # Event loop is shutting down.
            return

    def _debounce_project_update(self, project_name: str):
        try:
            loop = asyncio.get_running_loop()
            old = _debouncers.pop(project_name, None)
            if old:
                old.cancel()
            _debouncers[project_name] = loop.call_later(
                self.debounce_seconds,
                lambda: asyncio.create_task(self._trigger_update(project_name)),
            )
        except RuntimeError:
            pass

    async def _trigger_update(self, project_name: str):
        _debouncers.pop(project_name, None)
        try:
            from app.architecture import generate_architecture_map
            project_path = os.path.join(settings.WORKSPACE_ROOT, project_name)
            await generate_architecture_map(project_path)
        except Exception as exc:
            logger.error("Watchdog architecture refresh failed for %s: %s", project_name, exc)


class BackgroundWatcher:
    def __init__(self):
        self.observer = None
        self.handler = ProjectChangeHandler(debounce_seconds=10)
        self.is_running = False

    def start(self, loop: asyncio.AbstractEventLoop | None = None):
        if self.is_running:
            return
        if not WATCHDOG_AVAILABLE or PollingObserver is None:
            logger.warning("watchdog is not installed; background project watching is disabled")
            return
        target_dir = settings.WORKSPACE_ROOT
        if not os.path.exists(target_dir):
            logger.warning("Could not start Watchdog: WORKSPACE_ROOT '%s' does not exist", target_dir)
            return

        # PollingObserver threads cannot be restarted after stop/join.  Build a fresh
        # observer for each application lifespan.
        self.observer = PollingObserver(timeout=2.0)
        self.handler.set_loop(loop)
        for proj_name in os.listdir(target_dir):
            proj_path = os.path.join(target_dir, proj_name)
            if os.path.isdir(proj_path):
                self.observer.schedule(self.handler, proj_path, recursive=True)
        self.observer.start()
        self.is_running = True
        logger.info("Background Watchdog started for %s", target_dir)

    def stop(self):
        # Cancel pending debounce callbacks before the application loop disappears.
        for handle in list(_debouncers.values()):
            handle.cancel()
        _debouncers.clear()
        self.handler.set_loop(None)

        observer = self.observer
        if self.is_running and observer is not None:
            observer.stop()
            observer.join(timeout=5.0)
            if observer.is_alive():
                logger.warning("Background Watchdog did not stop within timeout")
            self.is_running = False
        self.observer = None


project_watcher = BackgroundWatcher()
