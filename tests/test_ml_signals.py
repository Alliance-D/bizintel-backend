"""Unit tests for the plain-language signal helpers in ml_opportunity_service -
the activity level, the localized opportunity type, the risk notes and the
recommendation sentence. These are pure functions, so they run without a
database and pin both the English and Kinyarwanda wording and every threshold."""

from app.services.ml_opportunity_service import (
    _activity_level,
    _localize_opportunity_type,
    _recommendation,
    _risk_notes,
)


class TestActivityLevel:
    def test_high_medium_low_thresholds_english(self):
        assert _activity_level(60) == "High"       # inclusive lower edge
        assert _activity_level(59.9) == "Medium"
        assert _activity_level(30) == "Medium"     # inclusive lower edge
        assert _activity_level(29.9) == "Low"
        assert _activity_level(0) == "Low"

    def test_kinyarwanda_wording(self):
        assert _activity_level(80, "rw") == "Byinshi"
        assert _activity_level(40, "rw") == "Bigereranije"
        assert _activity_level(10, "rw") == "Bike"

    def test_locale_prefix_variants_are_treated_as_kinyarwanda(self):
        assert _activity_level(80, "rw-RW") == "Byinshi"
        assert _activity_level(80, "kin") == "Byinshi"
        assert _activity_level(80, "en") == "High"


class TestLocalizeOpportunityType:
    def test_english_passes_through_unchanged(self):
        assert _localize_opportunity_type("Underserved", "en") == "Underserved"
        assert _localize_opportunity_type("Saturated", None) == "Saturated"

    def test_known_types_are_translated_to_kinyarwanda(self):
        assert _localize_opportunity_type("Underserved", "rw") == "Ahatarigera hagerwaho bihagije"
        assert _localize_opportunity_type("Saturated", "rw") == "Ahuzuye"

    def test_unknown_type_is_returned_as_is(self):
        assert _localize_opportunity_type("Something Else", "rw") == "Something Else"


class TestRiskNotes:
    def test_healthy_location_still_carries_the_undercount_caveat(self):
        notes = _risk_notes(gap_score=90, competition=30, confidence=80, access=80)
        assert len(notes) == 1
        assert "OSM" in notes[0]

    def test_low_confidence_and_low_access_add_notes(self):
        notes = _risk_notes(gap_score=90, competition=30, confidence=40, access=30)
        text = " ".join(notes)
        assert "confidence" in text.lower()
        assert "accessibility" in text.lower()

    def test_low_gap_flags_saturation(self):
        notes = _risk_notes(gap_score=10, competition=80, confidence=80, access=80)
        assert any("saturated" in n.lower() for n in notes)

    def test_kinyarwanda_notes_contain_no_english_leakage(self):
        notes = _risk_notes(gap_score=10, competition=80, confidence=40, access=30, locale="rw")
        assert "confidence" not in " ".join(notes).lower()


class TestRecommendation:
    def test_limited_confidence_short_circuits_to_exploratory_advice(self):
        msg = _recommendation(gap_score=90, confidence=40, competition_pressure=20, expected_count=5, observed_count=1)
        assert "exploratory" in msg.lower()

    def test_underserved_recommendation_names_expected_and_observed(self):
        msg = _recommendation(gap_score=85, confidence=80, competition_pressure=20, expected_count=4.2, observed_count=1)
        assert "underserved" in msg.lower()
        assert "4.2" in msg and "1" in msg

    def test_saturated_recommendation_points_elsewhere(self):
        msg = _recommendation(gap_score=10, confidence=80, competition_pressure=70, expected_count=2, observed_count=6)
        assert "saturated" in msg.lower()

    def test_missing_expected_count_renders_placeholder_not_crash(self):
        msg = _recommendation(gap_score=85, confidence=80, competition_pressure=20, expected_count=None, observed_count=1)
        assert "?" in msg
