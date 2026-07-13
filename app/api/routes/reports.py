from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.product import ReportCreate, UnifiedReportRequest, UnifiedReportExpandRequest
from app.services.report_service import build_location_report, persist_report
from app.services.pdf_report_service import build_pdf_report, build_unified_pdf
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
    """Build the unified report (single, area or compare), persist it, and return its public token."""
    report = build_unified_report(db, payload.model_dump())
    report_token = persist_unified_report(db, report)
    return {'report_token': report_token, 'report': report}


@router.get('/{report_token}')
def get_report(report_token: str, db: Session = Depends(get_db)) -> dict:
    """Fetch a persisted unified report by its public token (404 if missing)."""
    report = get_unified_report(db, report_token)
    if report is None:
        raise HTTPException(status_code=404, detail='Report not found')
    return {'report_token': report_token, 'report': report}


@router.get('/{report_token}/pdf')
def get_report_pdf(report_token: str, db: Session = Depends(get_db)) -> Response:
    """Render a persisted unified report to a branded, downloadable PDF."""
    report = get_unified_report(db, report_token)
    if report is None:
        raise HTTPException(status_code=404, detail='Report not found')
    pdf = build_unified_pdf(report)
    filename = f"bizintel-report-{report_token}.pdf"
    return Response(content=pdf, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@router.post('/{report_token}/expand')
def expand_report_candidate(report_token: str, payload: UnifiedReportExpandRequest, db: Session = Depends(get_db)) -> dict:
    """Expand one candidate cell of an area report into its own full point report."""
    entry = expand_candidate(db, report_token, payload.entry_index, payload.grid_id, payload.latitude, payload.longitude, payload.label)
    if entry is None:
        raise HTTPException(status_code=404, detail='Report or candidate not found')
    return entry
