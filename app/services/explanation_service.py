from app.geo.feature_extraction import LocationFeatures


def factor_status(score: float) -> str:
    if score >= 70:
        return "strong"
    if score >= 45:
        return "moderate"
    return "weak"


def build_explanations(features: LocationFeatures) -> dict:
    factors = [
        {
            "key": "demand",
            "label": "Demand strength",
            "score": features.demand_score,
            "status": factor_status(features.demand_score),
            "explanation": "Estimated customer demand based on nearby population, household and socio-economic indicators.",
        },
        {
            "key": "accessibility",
            "label": "Accessibility",
            "score": features.accessibility_score,
            "status": factor_status(features.accessibility_score),
            "explanation": "Road, transport and service-access conditions around the selected location.",
        },
        {
            "key": "commercial_activity",
            "label": "Commercial activity",
            "score": features.commercial_activity_score,
            "status": factor_status(features.commercial_activity_score),
            "explanation": "Nearby markets, shops, schools, banks, restaurants and other demand generators.",
        },
        {
            "key": "competition",
            "label": "Competition pressure",
            "score": features.competition_pressure,
            "status": factor_status(100 - features.competition_pressure),
            "explanation": "Estimated same-category saturation and nearby competitor pressure.",
        },
        {
            "key": "risk",
            "label": "Risk level",
            "score": features.risk_score,
            "status": factor_status(100 - features.risk_score),
            "explanation": "Composite risk from competition, weak access, and lower opportunity signals.",
        },
    ]

    strengths = []
    risks = []

    if features.demand_score >= 65:
        strengths.append("Strong demand indicators around the selected area.")
    else:
        risks.append("Demand indicators are not especially strong; verify customer flow physically.")

    if features.accessibility_score >= 65:
        strengths.append("Good accessibility signals from road and transport context.")
    else:
        risks.append("Accessibility may limit walk-in customers or repeat visits.")

    if features.competition_pressure >= 70:
        risks.append("Competition pressure appears high for this category.")
    elif features.competition_pressure <= 45:
        strengths.append("Competition pressure appears manageable, suggesting a possible gap.")

    next_steps = [
        "Visit the area during morning, midday and evening to validate foot traffic.",
        "Check nearby informal competitors that may not appear in official or OSM datasets.",
        "Confirm rent, visibility, frontage, utilities and customer access before committing.",
    ]

    return {"factors": factors, "strengths": strengths, "risks": risks, "next_steps": next_steps}
