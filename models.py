"""
models.py - Manages Pydantic models
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class SettingsRequest(BaseModel):
    connection_id: Optional[str] = None
    label: str = Field(default="", max_length=100)
    clear_external_api_key: bool = False
    server_type: str
    emby_url: str
    emby_user: str
    emby_pass: str
    gemini_key: Optional[str] = None
    ai_provider: Optional[str] = "ollama"
    ollama_url: Optional[str] = "http://localhost:11434"
    ollama_model: Optional[str] = "llama3.1"
    ollama_timeout: int = 120
    starred_models: Optional[List[str]] = Field(default_factory=list)
    external_api_key: Optional[str] = None

class ModelUpdateRequest(BaseModel):
    ollama_model: str

class MovieFinderRequest(BaseModel):
    user_id: str
    filters: Dict[str, Any] = Field(default_factory=dict)

class MusicFinderRequest(BaseModel):
    user_id: str
    filters: Dict[str, Any] = Field(default_factory=dict)

class FreshnessOptions(BaseModel):
    last_successful_builds: int = 0
    history_scope: str = "series"
    watched_within_days: int = 0
    exhaustion_policy: str = "shorter"

class DuplicatePolicyOptions(BaseModel):
    mode: str = "suppress"
    max_movies_per_franchise: int = 0

class SequencingItem(BaseModel):
    block_id: str
    take: int = 1

class SequencingOptions(BaseModel):
    mode: str = "sequential"
    pattern: Optional[List[SequencingItem]] = None
    exhaustion_policy: str = "continue"

class RuntimeBudgetOptions(BaseModel):
    mode: str = "off"
    target_minutes: int = 0
    allowed_overrun_minutes: int = 15
    end_local_time: Optional[str] = None
    timezone: Optional[str] = None

class MixOptions(BaseModel):
    freshness: Optional[FreshnessOptions] = Field(default_factory=FreshnessOptions)
    duplicate_policy: Optional[DuplicatePolicyOptions] = Field(default_factory=DuplicatePolicyOptions)
    sequencing: Optional[SequencingOptions] = Field(default_factory=SequencingOptions)
    runtime_budget: Optional[RuntimeBudgetOptions] = Field(default_factory=RuntimeBudgetOptions)

class MixedPlaylistRequest(BaseModel):
    user_id: str
    playlist_name: str
    blocks: Optional[List[Dict[str, Any]]] = None
    item_ids: Optional[List[str]] = None
    create_as_collection: bool = False
    mix_options: Optional[Dict[str, Any]] = None

class BuilderPreviewRequest(BaseModel):
    user_id: str
    blocks: List[Dict[str, Any]]
    mix_options: Optional[Dict[str, Any]] = None

class ReorderItemsRequest(BaseModel):
    user_id: str
    item_ids: List[str]

class AddItemsRequest(BaseModel):
    user_id: str
    blocks: List[Dict[str, Any]]
    mix_options: Optional[Dict[str, Any]] = None

class ScheduleDetails(BaseModel):
    frequency: str
    time: Optional[str] = None
    days_of_week: Optional[List[int]] = None
    interval_minutes: Optional[int] = None

class QuickPlaylistScheduleData(BaseModel):
    quick_playlist_type: str
    options: Optional[Dict[str, Any]] = None

class EnrichmentScheduleData(BaseModel):
    batch_size: int = Field(default=15, ge=1, le=500)
    timeout: int = Field(default=120, ge=10, le=600)

class ScheduleRequest(BaseModel):
    job_type: str
    playlist_name: str
    user_id: str
    schedule_details: ScheduleDetails
    preset_id: Optional[str] = None
    preset_name: Optional[str] = None
    blocks: Optional[List[Dict[str, Any]]] = None
    quick_playlist_data: Optional[QuickPlaylistScheduleData] = None
    enrichment_data: Optional[EnrichmentScheduleData] = None
    create_as_collection: bool = False
    mix_options: Optional[Dict[str, Any]] = None
    enabled: bool = True
    snoozed_until: Optional[str] = None
    trigger_sources: List[str] = ["clock", "watch", "library"]
    timezone: Optional[str] = None

class SnoozeRequest(BaseModel):
    minutes: Optional[int] = 60
    until: Optional[str] = None

class AiTweaks(BaseModel):
    threshold: float = 0.65
    limit: int = 25
    strictness: str = "genre_verified"
    temperature: float = 0.2
    target_size: int = 10
    only_unwatched: bool = False
    system_prompt: str = ""

class AiPromptRequest(BaseModel):
    prompt: str
    tweaks: Optional[AiTweaks] = None
    existing_blocks: Optional[List[Dict[str, Any]]] = None

class QuickBuildRequest(BaseModel):
    user_id: str
    playlist_name: str
    quick_build_type: str
    options: Dict[str, Any] = Field(default_factory=dict)

class DeleteItemRequest(BaseModel):
    item_id: str
    user_id: str

class RemoveFromPlaylistRequest(BaseModel):
    item_id_to_remove: str
    user_id: str

class ConvertItemRequest(BaseModel):
    item_id: str
    user_id: str
    new_name: str
    target_type: str
    delete_original: bool = False

class ResetWatchRequest(BaseModel):
    user_id: str
    season_number: Optional[int] = None

class ExternalPromptRequest(BaseModel):
    prompt: str
    preset_name: str

class ExternalBuildRequest(BaseModel):
    preset_name: str
    playlist_name: str

class ResetVectorDbRequest(BaseModel):
    preserve_enrichments: bool = True

class StartEnrichmentRequest(BaseModel):
    batch_size: int = 10
    max_items: Optional[int] = None

class BulkDeleteRequest(BaseModel):
    item_ids: List[str]
    user_id: str

class OverlapReportRequest(BaseModel):
    item_ids: Optional[List[str]] = None
    user_id: str

class ReplayRunRequest(BaseModel):
    playlist_name: Optional[str] = None
    user_id: Optional[str] = None
    dry_run: bool = False



