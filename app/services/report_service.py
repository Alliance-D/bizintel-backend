import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.services.ml_opportunity_service import assess_location_ml


def field_visit_checklist(category: str) -> list[str]:
    """Return the standard on-the-ground field-check list for a category."""
    return [
        'Visit at morning, midday and evening to see how the foot traffic changes.',
        f'Walk the street and count the {category} shops you can see, including small informal stalls.',
        'Check how easily customers reach the spot on foot from the nearest road and bus stop.',
        'Confirm the rent, lease terms and the condition of the unit.',
        'Ask nearby shopkeepers and residents what they still travel elsewhere to buy.',
    ]


def build_location_report(db: Session, payload: dict) -> dict:
    """Assemble a single-location report: scores, strengths, risks, competitors and next steps."""
    category = payload['business_category']
    latitude = float(payload['latitude'])
    longitude = float(payload['longitude'])
    assessment = assess_location_ml(db, latitude, longitude, category, 500)
    overall = assessment.get('overall', {})
    factors = assessment.get('factors', {})
    competition = assessment.get('competition', {})
    explanation = assessment.get('explanation') or {}
    score = float(overall.get('opportunity_score') or 0)
    confidence = float(overall.get('confidence_score') or 0)
    strengths = explanation.get('strengths') if isinstance(explanation, dict) else []
    risks = assessment.get('risk_notes') or (explanation.get('risks') if isinstance(explanation, dict) else []) or []
    if not strengths:
        if factors.get('demand_score', 0) >= 65:
            strengths.append('Demand signal is above average for this category.')
        if factors.get('accessibility_score', 0) >= 65:
            strengths.append('Accessibility signal is strong enough for shortlisting.')
        if factors.get('commercial_activity_score', 0) >= 65:
            strengths.append('Commercial activity around the location is strong.')
    if not risks and factors.get('competition_pressure', 0) >= 70:
        risks.append('Competition pressure is high and should be verified physically.')
    return {
        'title': payload['title'],
        'business_category': category,
        'latitude': latitude,
        'longitude': longitude,
        'source': assessment.get('source'),
        'nearest_grid_id': assessment.get('nearest_grid_id'),
        'model_version_id': assessment.get('model_version_id'),
        'overall_score': score,
        'opportunity_score': score,
        'opportunity_type': overall.get('opportunity_type'),
        'confidence': confidence,
        'executive_summary': assessment.get('recommendation') or f'This location scores {score:.0f} for {category}. Use this report for shortlisting and field validation, not as a guarantee.',
        'factors': [
            {'key': 'demand', 'label': 'Demand', 'score': factors.get('demand_score', 0)},
            {'key': 'accessibility', 'label': 'Accessibility', 'score': factors.get('accessibility_score', 0)},
            {'key': 'commercial_activity', 'label': 'Commercial activity', 'score': factors.get('commercial_activity_score', 0)},
            {'key': 'competition', 'label': 'Competition pressure', 'score': factors.get('competition_pressure', 0)},
        ],
        'strengths': strengths,
        'risks': risks,
        'competitive_analysis': {'competitors': competition},
        'field_visit_checklist': field_visit_checklist(category),
        'recommended_next_steps': explanation.get('field_checks') if isinstance(explanation, dict) else field_visit_checklist(category),
    }


def persist_report(db: Session, report: dict, saved_location_id: int | None = None) -> int | None:
    """Persist a generated report and return its id."""
    try:
        row = db.execute(text("""
            INSERT INTO app.location_reports (title, business_category, latitude, longitude, saved_location_id, report_payload, status)
            VALUES (:title, :category, :lat, :lon, :saved_location_id, CAST(:payload AS JSONB), 'ready')
            RETURNING id
        """), {'title': report['title'], 'category': report['business_category'], 'lat': report['latitude'], 'lon': report['longitude'], 'saved_location_id': saved_location_id, 'payload': json.dumps(report)}).first()
        db.commit()
        return int(row[0]) if row else None
    except Exception:
        db.rollback()
        return None
