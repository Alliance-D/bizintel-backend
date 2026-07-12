from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.opportunity_service import list_opportunity_cells, summarize_opportunity_map
router = APIRouter()
@router.get('/summary')
def insights_summary(category: str = Query('salon'), db: Session = Depends(get_db)) -> dict:
    """Dashboard summary for a category: analysed-cell counts, zone counts and the top cells."""
    cells = list_opportunity_cells(db, category=category, limit=25)
    summary = summarize_opportunity_map(cells)
    return {'headline': 'Kigali opportunity intelligence dashboard', 'category': category, 'cards': [{'label': 'Analysed opportunity cells', 'value': summary['total_cells']}, {'label': 'High-value zones', 'value': sum(1 for c in cells if c['zone_key'] in {'high_opportunity','underserved'})}, {'label': 'Saturated zones', 'value': sum(1 for c in cells if c['zone_key'] == 'saturated')}, {'label': 'Supported categories', 'value': 9}], 'zone_counts': summary['zone_counts'], 'top_cells': cells[:8], 'digest': ['Prioritize high-demand areas with moderate competition.', 'Validate informal competitors and rent availability.', 'Compare exact shop locations before committing.']}
