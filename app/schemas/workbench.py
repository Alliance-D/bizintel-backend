from typing import Any
from pydantic import BaseModel, Field


class SavedWorkbenchStateCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    business_category: str = Field(default='salon', max_length=80)
    center_lat: float | None = Field(default=None, ge=-3.0, le=-1.0)
    center_lon: float | None = Field(default=None, ge=28.0, le=31.5)
    zoom_level: float = Field(default=12, ge=1, le=22)
    active_layers: list[str] = Field(default_factory=lambda: ['opportunity'])
    filters: dict[str, Any] = Field(default_factory=dict)
    selected_locations: list[dict[str, Any]] = Field(default_factory=list)
    state_payload: dict[str, Any] = Field(default_factory=dict)
    is_pinned: bool = False


class SavedWorkbenchStateUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    business_category: str | None = Field(default=None, max_length=80)
    center_lat: float | None = Field(default=None, ge=-3.0, le=-1.0)
    center_lon: float | None = Field(default=None, ge=28.0, le=31.5)
    zoom_level: float | None = Field(default=None, ge=1, le=22)
    active_layers: list[str] | None = None
    filters: dict[str, Any] | None = None
    selected_locations: list[dict[str, Any]] | None = None
    state_payload: dict[str, Any] | None = None
    is_pinned: bool | None = None


class UserPreferencesUpdate(BaseModel):
    default_business_category: str | None = None
    default_radius_meters: int | None = Field(default=None, ge=100, le=5000)
    theme: str | None = None
    map_style: str | None = None
    notification_frequency: str | None = None
    preferred_districts: list[str] | None = None
    preferred_budget_level: str | None = None
