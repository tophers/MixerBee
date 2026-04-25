"""
app/ai/__init__.py - AI Smart Block init .
"""


from .orchestrator import generate_smart_blocks, process_enrichment_queue
from .vector_store import calculate_library_iq

__all__ = ["generate_smart_blocks", "process_enrichment_queue", "calculate_library_iq"]
