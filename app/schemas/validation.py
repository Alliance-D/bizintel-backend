from pydantic import BaseModel, Field
from typing import Optional

class ValidationPointCreate(BaseModel):
    business_category: str
    latitude: float = Field(ge=-3.0, le=-1.0)
    longitude: float = Field(ge=28.0, le=31.5)
    observed_activity: Optional[str] = None
    pedestrian_level: Optional[str] = None
    visible_competitors: Optional[int] = Field(default=None, ge=0)
    informal_competitors: Optional[int] = Field(default=None, ge=0)
    visibility_score: Optional[int] = Field(default=None, ge=1, le=5)
    rent_signal: Optional[str] = None
    model_score: Optional[float] = None
    model_label: Optional[str] = None
    validator_notes: Optional[str] = None
    photo_url: Optional[str] = None
