"""Optional filesystem watcher for architecture refreshes."""
from __future__ import annotations

import asyncio
import logging
import os
from app.config import settings

logger = logging.getLogger(__name__)
_debouncers = {}

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

    def on_modified(self, event):
        pass

    def on_created(self, event):
        self._handle_event(event)

    def on_deleted(self, event):
        self._handle_event(event)

    def _handle_event(self, event):
        if getattr(event, "is_directory", False):
            return
        path = getattr(event, "src_path", "")
        if any(ignore in path for ignore in [".git", "node_modules", "venv", "__pycache__", ".venv"]):
            return
        rel_path = os.path.relpath(path, settings.WORKSPACE_ROOT)
        parts = rel_path.split(os.sep)
        if len(parts) < 2:
            return
        project_name = parts[0]
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(self._debounce_project_update, project_name)
        except RuntimeError:
            pass

    def _debounce_project_update(self, project_name: str):
        try:
            loop = asyncio.get_running_loop()
            if project_name in _debouncers:
                _debouncers[project_name].cancel()
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
        self.observer = PollingObserver(timeout=2.0) if WATCHDOG_AVAILABLE else None
        self.handler = ProjectChangeHandler(debounce_seconds=10)
        self.is_running = False

    def start(self):
        if self.is_running:
            return
        if not WATCHDOG_AVAILABLE or self.observer is None:
            logger.warning("watchdog is not installed; background project watching is disabled")
            return
        target_dir = settings.WORKSPACE_ROOT
        if not os.path.exists(target_dir):
            logger.warning("Could not start Watchdog: WORKSPACE_ROOT '%s' does not exist", target_dir)
            return
        for proj_name in os.listdir(target_dir):
            proj_path = os.path.join(target_dir, proj_name)
            if os.path.isdir(proj_path):
                self.observer.schedule(self.handler, proj_path, recursive=True)
        self.observer.start()
        self.is_running = True
        logger.info("Background Watchdog started for %s", target_dir)

    def stop(self):
        if self.is_running and self.observer is not None:
            self.observer.stop()
            self.observer.join()
            self.is_running = False


project_watcher = BackgroundWatcher()
