from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.product import ReportCreate, UnifiedReportRequest, UnifiedReportExpandRequest
from app.services.report_service import build_location_report, persist_report
from app.services.pdf_report_service import build_pdf_report
from app.services.unified_report_service import build_unified_report, persist_unified_report, get_unified_report, expand_candidate
router = APIRouter()
@router.post('/generate')
def generate_report(payload: ReportCreate, db: Session = Depends(get_db)) -> dict:
    """Build a single-location report and persist it, returning its id."""
    report = build_location_report(db, payload.model_dump())
    report_id = persist_report(db, report, payload.saved_location_id)
    return {'report_id': report_id, 'report': report}


@router.post('/pdf')
def generate_report_pdf(payload: ReportCreate, db: Session = Depends(get_db)) -> Response:
    """Build a single-location report and return it as a downloadable PDF."""
    report = build_location_report(db, payload.model_dump())
    pdf = build_pdf_report(report)
    return Response(content=pdf, media_type='application/pdf', headers={'Content-Disposition': 'attachment; filename=location_report.pdf'})


@router.post('/build')
def build_report(payload: UnifiedReportRequest, db: Session = Depends(get_db)) -> dict:
    """Build the unified report (single, area or compare) and persist it, returning its id."""
    report = build_unified_report(db, payload.model_dump())
    report_id = persist_unified_report(db, report)
    return {'report_id': report_id, 'report': report}


@router.get('/{report_id}')
def get_report(report_id: int, db: Session = Depends(get_db)) -> dict:
    """Fetch a persisted unified report by id (404 if missing)."""
    report = get_unified_report(db, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail='Report not found')
    return {'report_id': report_id, 'report': report}


@router.post('/{report_id}/expand')
def expand_report_candidate(report_id: int, payload: UnifiedReportExpandRequest, db: Session = Depends(get_db)) -> dict:
    """Expand one candidate cell of an area report into its own full point report."""
    entry = expand_candidate(db, report_id, payload.entry_index, payload.grid_id, payload.latitude, payload.longitude, payload.label)
    if entry is None:
        raise HTTPException(status_code=404, detail='Report or candidate not found')
    return entry
