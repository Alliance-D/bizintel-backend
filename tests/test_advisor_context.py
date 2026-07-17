from app.services.ai_advisor_service import build_context_prompt

ASSESSMENT = {
    "business_category": "pharmacy",
    "location_label": "the part of Kimihurura around Ituze village",
    "overall": {
        "expected_count": 6.3, "observed_count": 7.0, "gap": -0.7,
        "gap_score": 5.4, "opportunity_type": "Saturated", "viability": 0.82,
    },
    "competition": {"within_300m": 1, "within_500m": 3, "within_1000m": 7},
}


def test_prompt_includes_core_gap_numbers():
    prompt = build_context_prompt(ASSESSMENT)
    assert "6.3" in prompt
    assert "7.0" in prompt
    assert "Saturated" in prompt
    assert "the part of Kimihurura around Ituze village" in prompt


def test_prompt_omits_user_context_when_not_given():
    prompt = build_context_prompt(ASSESSMENT)
    assert "budget" not in prompt.lower()
    assert "User-stated" not in prompt


def test_prompt_includes_user_context_with_never_invent_caveat():
    prompt = build_context_prompt(ASSESSMENT, {"budget": "300000 RWF/month", "notes": "small storefront"})
    assert "300000 RWF/month" in prompt
    assert "small storefront" in prompt
    assert "never invent specific numbers" in prompt.lower()


def test_prompt_includes_only_budget_when_notes_missing():
    prompt = build_context_prompt(ASSESSMENT, {"budget": "300000 RWF/month", "notes": ""})
    assert "300000 RWF/month" in prompt
    assert "User-stated other context" not in prompt
