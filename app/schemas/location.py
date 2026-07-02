from pydantic import BaseModel, Field
from typing import Literal

BusinessCategory = Literal[
    "salon",
    "barbershop",
    "beauty_salon",
    "pharmacy",
    "cafe",
    "restaurant",
    "grocery",
    "retail",
    "mobile_money",
]


class LocationPoint(BaseModel):
    latitude: float = Field(..., ge=-2.2, le=-1.7)
    longitude: float = Field(..., ge=29.8, le=30.3)


class ScoutAssessmentRequest(LocationPoint):
    business_category: BusinessCategory
    radius_meters: int = Field(default=500, ge=100, le=2000)
    budget_level: Literal["low", "medium", "high"] = "medium"
    risk_tolerance: Literal["low", "medium", "high"] = "medium"


class FactorScore(BaseModel):
    key: str
    label: str
    score: float = Field(..., ge=0, le=100)
    status: Literal["weak", "moderate", "strong"]
    explanation: str


class ScoutAssessmentResponse(BaseModel):
    opportunity_score: float = Field(..., ge=0, le=100)
    category: str
    opportunity_type: str
    confidence: Literal["low", "medium", "high"]
    factors: list[FactorScore]
    strengths: list[str]
    risks: list[str]
    next_steps: list[str]
