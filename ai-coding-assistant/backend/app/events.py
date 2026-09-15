import logging
import asyncio
from typing import Callable, Dict, List, Any
from app.job_service import enqueue_job

logger = logging.getLogger(__name__)

# Dictionary of event_name -> list of callback functions
_EVENT_LISTENERS: Dict[str, List[Callable]] = {}

def subscribe(event_name: str, handler: Callable):
    """Subscribe to an event. Handler can be sync or async."""
    if event_name not in _EVENT_LISTENERS:
        _EVENT_LISTENERS[event_name] = []
    _EVENT_LISTENERS[event_name].append(handler)
    logger.info(f"Subscribed handler {handler.__name__} to event {event_name}")

async def dispatch(event_name: str, payload: dict):
    """Dispatch an event to all subscribers."""
    logger.info(f"Event dispatched: {event_name}")
    listeners = _EVENT_LISTENERS.get(event_name, [])
    
    for handler in listeners:
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(payload)
            else:
                handler(payload)
        except Exception as e:
            logger.error(f"Error handling event {event_name} by {handler.__name__}: {e}")

def enqueue_job_on_event(job_type: str):
    """Helper to quickly route an event payload to a background job queue."""
    def handler(payload: dict):
        enqueue_job(job_type, payload)
    return handler
