"""
models.py - Pydantic models for the MixerBee API.
"""

from typing import List, Optional, Dict
from pydantic import BaseModel, Field

class SettingsRequest(BaseModel):
    server_type: str
    emby_url: str
    emby_user: str
    emby_pass: str
    gemini_key: Optional[str] = None

class MovieFinderRequest(BaseModel):
    user_id: str
    filters: dict = {}

class MusicFinderRequest(BaseModel):
    user_id: str
    filters: dict = {}

class MixedPlaylistRequest(BaseModel):
    user_id: str
    playlist_name: str
    blocks: Optional[List[dict]] = None
    create_as_collection: bool = False

class BuilderPreviewRequest(BaseModel):
    user_id: str
    blocks: List[Dict]

class AddItemsRequest(BaseModel):
    user_id: str
    blocks: List[Dict]

class ScheduleDetails(BaseModel):
    frequency: str
    time: str
    days_of_week: Optional[List[int]] = Field(None, ge=0, le=6)

class QuickPlaylistScheduleData(BaseModel):
    quick_playlist_type: str
    options: Optional[Dict] = None

class ScheduleRequest(BaseModel):
    job_type: str
    playlist_name: str
    user_id: str
    schedule_details: ScheduleDetails
    preset_name: Optional[str] = None
    blocks: Optional[List[Dict]] = None
    quick_playlist_data: Optional[QuickPlaylistScheduleData] = None

class AiPromptRequest(BaseModel):
    prompt: str

class QuickBuildRequest(BaseModel):
    user_id: str
    playlist_name: str
    quick_build_type: str
    options: Dict = {}

class MixRequest(BaseModel):
    shows: List[str] = []
    count: int = 5
    playlist: str = "MixerBee Playlist"
    delete: bool = False
    verbose: bool = False
    target_uid: Optional[str] = None

class DeleteItemRequest(BaseModel):
    item_id: str
    user_id: str

class RemoveFromPlaylistRequest(BaseModel):
    item_id_to_remove: str
    user_id: str