"""
models.py - Pydantic models for the MixerBee API.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class SettingsRequest(BaseModel):
    server_type: str
    emby_url: str
    emby_user: str
    emby_pass: str
    gemini_key: Optional[str] = None

class MovieFinderRequest(BaseModel):
    user_id: str
    filters: Dict[str, Any] = Field(default_factory=dict)

class MusicFinderRequest(BaseModel):
    user_id: str
    filters: Dict[str, Any] = Field(default_factory=dict)

class MixedPlaylistRequest(BaseModel):
    user_id: str
    playlist_name: str
    blocks: Optional[List[Dict[str, Any]]] = None
    create_as_collection: bool = False

class BuilderPreviewRequest(BaseModel):
    user_id: str
    blocks: List[Dict[str, Any]]

class AddItemsRequest(BaseModel):
    user_id: str
    blocks: List[Dict[str, Any]]

class ScheduleDetails(BaseModel):
    frequency: str
    time: str
    days_of_week: Optional[List[int]] = None

class QuickPlaylistScheduleData(BaseModel):
    quick_playlist_type: str
    options: Optional[Dict[str, Any]] = None

class ScheduleRequest(BaseModel):
    job_type: str
    playlist_name: str
    user_id: str
    schedule_details: ScheduleDetails
    preset_name: Optional[str] = None
    blocks: Optional[List[Dict[str, Any]]] = None
    quick_playlist_data: Optional[QuickPlaylistScheduleData] = None
    create_as_collection: bool = False

class AiPromptRequest(BaseModel):
    prompt: str

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