"""
app/ai/__init__.py - AI Smart Block init .
"""


from .enrichment_manager import stop_all_for_account as stop_account_ai_work
from .orchestrator import generate_smart_blocks, process_enrichment_queue
from .vector_store import calculate_library_iq
from .assist_orchestrator import (
    AssistError,
    AssistPinUnavailable,
    assist_availability,
    run_assist_turn,
)

__all__ = [
    "generate_smart_blocks",
    "stop_account_ai_work",
    "process_enrichment_queue",
    "calculate_library_iq",
    "assist_availability",
    "run_assist_turn",
    "AssistError",
    "AssistPinUnavailable",
]
