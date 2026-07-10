from pydantic import BaseModel, Field
from typing import Literal

class LocationPoint(BaseModel):
    latitude: float = Field(..., ge=-3.0, le=-1.0)
    longitude: float = Field(..., ge=28.0, le=31.5)
    label: str | None = None

class OpportunityMapQuery(BaseModel):
    business_category: str = 'salon'
    district: str | None = None
    mode: Literal['opportunity','demand','competition','access','saturation'] = 'opportunity'
    limit: int = Field(50, ge=1, le=500)

class CompetitiveAnalysisRequest(BaseModel):
    latitude: float
    longitude: float
    business_category: str = 'salon'
    radius_meters: int = Field(1000, ge=300, le=3000)

class CompareLocationsRequest(BaseModel):
    business_category: str = 'salon'
    locations: list[LocationPoint] = Field(..., min_length=2, max_length=8)
    locale: str | None = None

class SavedLocationCreate(BaseModel):
    label: str
    business_category: str
    latitude: float
    longitude: float
    notes: str | None = None

class WatchlistCreate(BaseModel):
    name: str
    business_category: str | None = None
    district: str | None = None
    alert_frequency: Literal['daily','weekly','monthly'] = 'weekly'

class ReportCreate(BaseModel):
    title: str
    business_category: str
    latitude: float
    longitude: float
    saved_location_id: int | None = None

class UnifiedReportPoint(BaseModel):
    mode: Literal['point'] = 'point'
    latitude: float = Field(..., ge=-3.0, le=-1.0)
    longitude: float = Field(..., ge=28.0, le=31.5)
    label: str | None = None

class UnifiedReportArea(BaseModel):
    mode: Literal['area'] = 'area'
    district: str
    sector: str | None = None
    cell: str | None = None
    label: str | None = None

class UnifiedReportRequest(BaseModel):
    business_category: str
    locations: list[UnifiedReportPoint | UnifiedReportArea] = Field(..., min_length=1, max_length=4)
    budget: str | None = Field(None, max_length=300)
    notes: str | None = Field(None, max_length=500)
    locale: str | None = None

class UnifiedReportExpandRequest(BaseModel):
    entry_index: int = Field(..., ge=0)
    grid_id: str
    latitude: float
    longitude: float
    label: str | None = None
