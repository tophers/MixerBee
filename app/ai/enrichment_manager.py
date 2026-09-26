"""
app/ai/enrichment_manager.py - On-Demand Enrichment background manager.
Provides per-connection concurrency guard, cooperative cancellation, progress tracking,
and scheduler coordination.
"""

import time
import threading
from typing import Dict, Any, Optional
from app.logger import get_logger

logger = get_logger("MixerBee.EnrichmentManager")

class EnrichmentWorkerState:
    def __init__(self, connection_id: str):
        self.connection_id = connection_id
        self.status = "idle"  # idle, running, stopping, completed, error
        self.total_items = 0
        self.processed_items = 0
        self.succeeded_items = 0
        self.failed_items = 0
        self.start_time: Optional[float] = None
        self.finish_time: Optional[float] = None
        self.last_message = ""
        self.stop_requested = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def to_dict(self) -> Dict[str, Any]:
        elapsed = 0.0
        if self.start_time:
            end = self.finish_time if self.finish_time else time.time()
            elapsed = round(end - self.start_time, 1)

        return {
            "connection_id": self.connection_id,
            "status": self.status,
            "total_items": self.total_items,
            "processed_items": self.processed_items,
            "succeeded_items": self.succeeded_items,
            "failed_items": self.failed_items,
            "remaining_items": max(0, self.total_items - self.processed_items),
            "start_time": self.start_time,
            "finish_time": self.finish_time,
            "elapsed_seconds": elapsed,
            "last_message": self.last_message,
        }

_workers: Dict[str, EnrichmentWorkerState] = {}
_worker_locks: Dict[str, threading.Lock] = {}
_manager_lock = threading.Lock()


def _get_worker(connection_id: str) -> EnrichmentWorkerState:
    with _manager_lock:
        if connection_id not in _workers:
            _workers[connection_id] = EnrichmentWorkerState(connection_id)
        if connection_id not in _worker_locks:
            _worker_locks[connection_id] = threading.Lock()
        return _workers[connection_id]


def acquire_enrichment_guard(connection_id: str) -> bool:
    """Attempts to acquire the enrichment lock non-blockingly."""
    _get_worker(connection_id)
    lock = _worker_locks[connection_id]
    acquired = lock.acquire(blocking=False)
    if not acquired:
        return False
    state = _workers[connection_id]
    if state.status == "running":
        lock.release()
        return False
    return True


def release_enrichment_guard(connection_id: str):
    """Releases the enrichment lock."""
    with _manager_lock:
        lock = _worker_locks.get(connection_id)
    if lock and lock.locked():
        try:
            lock.release()
        except RuntimeError:
            pass


class enrichment_guard:
    """Context manager for acquiring the per-connection enrichment lock."""
    def __init__(self, connection_id: str):
        self.connection_id = connection_id
        self.acquired = False

    def __enter__(self):
        self.acquired = acquire_enrichment_guard(self.connection_id)
        return self.acquired

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            release_enrichment_guard(self.connection_id)


def get_enrichment_status(connection_id: str, media=None) -> Dict[str, Any]:
    """Returns current enrichment run status and queue size for a connection."""
    state = _get_worker(connection_id)
    data = state.to_dict()

    # Query ChromaDB for actual un-enriched count if media or connection is active
    try:
        from .vector_store import get_media_collection
        if media:
            with media.as_active():
                col = get_media_collection()
                unprocessed = col.get(where={"is_enriched": False}, include=[])
                data["queue_depth"] = len(unprocessed.get("ids", []))
        else:
            col = get_media_collection()
            unprocessed = col.get(where={"is_enriched": False}, include=[])
            data["queue_depth"] = len(unprocessed.get("ids", []))
    except Exception as e:
        logger.debug("Failed to query ChromaDB for queue depth: %s", e)
        data["queue_depth"] = max(0, data["total_items"] - data["processed_items"])

    return data


def start_enrichment(
    connection_id: str,
    media,
    batch_size: int = 10,
    max_items: Optional[int] = None
) -> Dict[str, Any]:
    """
    Validates AI configuration and starts a background enrichment worker.
    Raises RuntimeError (or ValueError) if already running or invalid config.
    """
    # 1. Validate AI settings
    ai_settings = media.connection.ai_settings or {}
    provider = ai_settings.get("AI_PROVIDER", "gemini")
    if provider == "gemini":
        gemini_key = ai_settings.get("GEMINI_API_KEY", "").strip()
        if not gemini_key:
            raise ValueError("Gemini API Key is not configured for this connection.")
    elif provider == "ollama":
        ollama_url = ai_settings.get("OLLAMA_URL", "").strip()
        if not ollama_url:
            raise ValueError("Ollama URL is not configured for this connection.")
    else:
        raise ValueError(f"Unknown AI Provider: {provider}")

    state = _get_worker(connection_id)
    lock = _worker_locks[connection_id]

    if not lock.acquire(blocking=False):
        raise RuntimeError("Enrichment is already in progress for this connection.")

    if state.status == "running":
        lock.release()
        raise RuntimeError("Enrichment is already in progress for this connection.")

    # Calculate starting queue size
    try:
        from .vector_store import get_media_collection
        with media.as_active():
            col = get_media_collection()
            unprocessed = col.get(where={"is_enriched": False}, include=[])
            queue_len = len(unprocessed.get("ids", []))
    except Exception:
        queue_len = 0

    state.status = "running"
    state.total_items = queue_len if max_items is None else min(queue_len, max_items)
    state.processed_items = 0
    state.succeeded_items = 0
    state.failed_items = 0
    state.start_time = time.time()
    state.finish_time = None
    state.last_message = f"Enrichment started ({state.total_items} items in queue)."
    state.stop_requested.clear()

    def _worker():
        try:
            from .orchestrator import process_enrichment_queue
            logger.info("Enrichment worker thread started for connection %s", connection_id)

            while not state.stop_requested.is_set():
                current_batch = batch_size
                if max_items is not None:
                    remaining_allowed = max_items - state.processed_items
                    if remaining_allowed <= 0:
                        break
                    current_batch = min(current_batch, remaining_allowed)

                res = process_enrichment_queue(
                    batch_size=current_batch,
                    timeout=120,
                    media=media,
                    stop_event=state.stop_requested
                )

                if res.get("status") == "error":
                    state.status = "error"
                    state.last_message = f"Enrichment error: {res.get('log', ['Unknown error'])[0]}"
                    break

                batch_proc = res.get("processed", 0)
                batch_succ = res.get("success", 0)
                batch_failed = batch_proc - batch_succ

                state.processed_items += batch_proc
                state.succeeded_items += batch_succ
                state.failed_items += batch_failed

                if batch_proc == 0:
                    state.status = "completed"
                    state.last_message = "Queue is empty. Library is 100% enriched."
                    break

                if max_items is not None and state.processed_items >= max_items:
                    state.status = "completed"
                    state.last_message = f"Reached requested limit of {max_items} items."
                    break

                time.sleep(0.2)

            if state.stop_requested.is_set():
                state.status = "completed"
                state.last_message = "Enrichment stopped by user."

        except Exception as e:
            logger.error("Enrichment worker crashed for connection %s: %s", connection_id, e, exc_info=True)
            state.status = "error"
            state.last_message = str(e)
        finally:
            state.finish_time = time.time()
            try:
                lock.release()
            except RuntimeError:
                pass
            logger.info(
                "Enrichment worker finished for connection %s: processed=%d, success=%d, failed=%d",
                connection_id, state.processed_items, state.succeeded_items, state.failed_items
            )

    t = threading.Thread(target=_worker, name=f"enrichment-{connection_id}", daemon=True)
    state.thread = t
    t.start()

    return state.to_dict()


def stop_enrichment(connection_id: str) -> Dict[str, Any]:
    """Signals an active enrichment worker to halt cooperatively."""
    state = _get_worker(connection_id)
    if state.status != "running":
        return {
            "status": "ok",
            "message": f"Enrichment is not currently running (status: {state.status}).",
            "state": state.to_dict()
        }

    state.stop_requested.set()
    state.status = "stopping"
    state.last_message = "Stop requested, waiting for current item to finish..."
    return {
        "status": "ok",
        "message": "Enrichment stop requested.",
        "state": state.to_dict()
    }
