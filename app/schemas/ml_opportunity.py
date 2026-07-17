from pydantic import BaseModel, Field


class MLAssessRequest(BaseModel):
    latitude: float = Field(..., ge=-3.0, le=-1.0)
    longitude: float = Field(..., ge=28.0, le=31.5)
    business_category: str = Field("salon")
    radius_meters: int = Field(500, ge=100, le=3000)


class CategoryProfileResponse(BaseModel):
    category_key: str
    display_name: str
    description: str | None = None
    weights: dict
    confidence_threshold: float


class OpportunityZoneResponse(BaseModel):
    grid_id: str
    business_category: str
    opportunity_score: float
    opportunity_rank: float | None = None
    opportunity_type: str | None = None
    latitude: float
    longitude: float
    explanation: dict | None = None
