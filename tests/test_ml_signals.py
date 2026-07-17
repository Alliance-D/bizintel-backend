"""Unit tests for the plain-language signal helpers in ml_opportunity_service -
the localized opportunity type, the risk notes and the recommendation sentence.
These are pure functions, so they run without a database and pin both the English
and Kinyarwanda wording. They read only the model's own outputs (the gap
percentile and the viability probability), not the retired composite scores."""

from app.services.ml_opportunity_service import (
    _localize_opportunity_type,
    _recommendation,
    _risk_notes,
)


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
        notes = _risk_notes(gap_score=90, viability=0.8)
        assert len(notes) == 1
        assert "OSM" in notes[0]

    def test_low_viability_adds_a_weak_support_note(self):
        notes = _risk_notes(gap_score=90, viability=0.2)
        assert any("weakly support" in n.lower() for n in notes)

    def test_low_gap_flags_saturation(self):
        notes = _risk_notes(gap_score=10, viability=0.8)
        assert any("saturated" in n.lower() for n in notes)

    def test_kinyarwanda_notes_contain_no_english_leakage(self):
        notes = _risk_notes(gap_score=10, viability=0.2, locale="rw")
        text = " ".join(notes).lower()
        assert "saturated" not in text
        assert "weakly support" not in text


class TestRecommendation:
    def test_low_viability_short_circuits_to_exploratory_advice(self):
        msg = _recommendation(gap_score=90, expected_count=5, observed_count=1, viability=0.2)
        assert "exploratory" in msg.lower()

    def test_underserved_recommendation_names_expected_and_observed(self):
        msg = _recommendation(gap_score=85, expected_count=4.2, observed_count=1, viability=0.8)
        assert "underserved" in msg.lower()
        assert "4.2" in msg and "1" in msg

    def test_saturated_recommendation_points_elsewhere(self):
        msg = _recommendation(gap_score=10, expected_count=2, observed_count=6, viability=0.8)
        assert "saturated" in msg.lower()

    def test_missing_expected_count_renders_placeholder_not_crash(self):
        msg = _recommendation(gap_score=85, expected_count=None, observed_count=1, viability=0.8)
        assert "?" in msg

    def test_missing_viability_does_not_short_circuit(self):
        msg = _recommendation(gap_score=85, expected_count=4.2, observed_count=1, viability=None)
        assert "underserved" in msg.lower()
