import asyncio
import os
import logging
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler
from app.config import settings

logger = logging.getLogger(__name__)

# A simple debounce queue: maps project_name -> asyncio.TimerHandle or task
_debouncers = {}

class ProjectChangeHandler(FileSystemEventHandler):
    def __init__(self, debounce_seconds: int = 10):
        self.debounce_seconds = debounce_seconds

    def on_modified(self, event):
        # Ignore logic edits for Architecture Map; only care about structural changes
        pass
        
    def on_created(self, event):
        self._handle_event(event)
        
    def on_deleted(self, event):
        self._handle_event(event)
        
    def _handle_event(self, event):
        if event.is_directory:
            return
            
        # Ignore common noise
        if any(ignore in event.src_path for ignore in [".git", "node_modules", "venv", "__pycache__", ".venv"]):
            return
            
        # Extract project name from path (WorkspaceRoot / ProjectName / ...)
        rel_path = os.path.relpath(event.src_path, settings.WORKSPACE_ROOT)
        parts = rel_path.split(os.sep)
        if len(parts) >= 2:
            project_name = parts[0]
            # If the user edited a file in the workspace root directly (not in a project folder), ignore
            if project_name == rel_path:
                return
                
            # watchdog runs on a background thread. We must schedule debouncing on the main asyncio loop.
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(self._debounce_project_update, project_name)
            except RuntimeError:
                pass

    def _debounce_project_update(self, project_name: str):
        try:
            loop = asyncio.get_running_loop()
            
            # If there's an existing timer for this project, cancel it
            if project_name in _debouncers:
                _debouncers[project_name].cancel()
                
            # Schedule a new timer
            _debouncers[project_name] = loop.call_later(
                self.debounce_seconds,
                lambda: asyncio.create_task(self._trigger_update(project_name))
            )
        except RuntimeError:
            pass

    async def _trigger_update(self, project_name: str):
        # Remove from debouncers
        if project_name in _debouncers:
            del _debouncers[project_name]
            
        logger.info(f"[Watchdog] 10 seconds of silence detected. Silently updating Architecture Map for '{project_name}'...")
        
        try:
            from app.architecture import generate_architecture_map
            project_path = os.path.join(settings.WORKSPACE_ROOT, project_name)
            await generate_architecture_map(project_path)
            logger.info(f"[Watchdog] Silent Architecture Map update complete for '{project_name}'.")
        except Exception as e:
            logger.error(f"[Watchdog] Silent update failed for '{project_name}': {e}")


class BackgroundWatcher:
    def __init__(self):
        self.observer = PollingObserver(timeout=2.0)
        self.handler = ProjectChangeHandler(debounce_seconds=10)
        self.is_running = False

    def start(self):
        if not self.is_running:
            target_dir = settings.WORKSPACE_ROOT
            if os.path.exists(target_dir):
                for proj_name in os.listdir(target_dir):
                    proj_path = os.path.join(target_dir, proj_name)
                    if not os.path.isdir(proj_path):
                        continue
                    # Single recursive watch per project — noise filtering is in the event handler
                    self.observer.schedule(self.handler, proj_path, recursive=True)
                    
                self.observer.start()
                self.is_running = True
                logger.info(f"Background Watchdog started for {target_dir}")
            else:
                logger.warning(f"Could not start Watchdog: WORKSPACE_ROOT '{target_dir}' does not exist.")

    def stop(self):
        if self.is_running:
            self.observer.stop()
            self.observer.join()
            self.is_running = False
            logger.info("Background Watchdog stopped.")

# Singleton instance
project_watcher = BackgroundWatcher()
