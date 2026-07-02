from pydantic import BaseModel
from typing import List, Optional

class ReadinessArea(BaseModel):
    area: str
    total_items: int
    done_items: int
    open_items: int
    completion_pct: float

class DemoScenario(BaseModel):
    id: int
    title: str
    persona: str
    business_category: str
    location_label: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    objective: str
    expected_story: str

class ReadinessResponse(BaseModel):
    status: str
    summary: List[ReadinessArea]
    demo_scenarios: List[DemoScenario]
    next_actions: List[str]
