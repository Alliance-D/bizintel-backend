from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.product import ReportCreate
from app.services.report_service import build_location_report, persist_report
router = APIRouter()
@router.post('/generate')
def generate_report(payload: ReportCreate, db: Session = Depends(get_db)) -> dict:
    report = build_location_report(db, payload.model_dump())
    report_id = persist_report(db, report, payload.saved_location_id)
    return {'report_id': report_id, 'report': report}


from fastapi import Response
from app.services.pdf_report_service import build_pdf_report

@router.post('/pdf')
def generate_report_pdf(payload: ReportCreate, db: Session = Depends(get_db)) -> Response:
    report = build_location_report(db, payload.model_dump())
    pdf = build_pdf_report(report)
    return Response(content=pdf, media_type='application/pdf', headers={'Content-Disposition': 'attachment; filename=location_report.pdf'})
