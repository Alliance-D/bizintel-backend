from pydantic import BaseModel, Field


class CellInsightRequest(BaseModel):
    latitude: float = Field(..., ge=-3.0, le=-1.0)
    longitude: float = Field(..., ge=28.0, le=31.5)
    business_category: str = Field('salon')
    radius_meters: int = Field(500, ge=100, le=3000)


class ExperienceEventRequest(BaseModel):
    event_name: str
    business_category: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    payload: dict = Field(default_factory=dict)
    session_id: str | None = None
