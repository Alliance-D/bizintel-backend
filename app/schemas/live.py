from pydantic import BaseModel, Field


class LocationContextRequest(BaseModel):
    latitude: float = Field(..., ge=-2.3, le=-1.6)
    longitude: float = Field(..., ge=29.7, le=30.4)
    business_category: str = "salon"
    radius_meters: int = Field(default=1000, ge=100, le=3000)


class LayerReadiness(BaseModel):
    layer: str
    rows: int
    last_loaded: str | None = None
    status: str


class LocationContextResponse(BaseModel):
    latitude: float
    longitude: float
    business_category: str
    opportunity: dict
    population: dict
    nearby_features: dict
    data_confidence: dict
