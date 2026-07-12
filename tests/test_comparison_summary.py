"""Unit tests for the head-to-head comparison summary - the one-sentence reason
the winning area edges the runner-up. Pure function over two result dicts, so it
runs without a database and pins the founder-facing wording in both languages."""

from app.services.unified_report_service import _comparison_summary, _num


def _loc(label, expected, observed, people):
    return {"label": label, "expected_count": expected, "observed_count": observed, "people_within_1km": people}


class TestNum:
    def test_coerces_and_defaults_safely(self):
        assert _num("3.5") == 3.5
        assert _num(None) == 0.0
        assert _num("not-a-number") == 0.0


class TestComparisonSummary:
    def test_more_unmet_demand_is_cited_when_winner_gap_is_wider(self):
        winner = _loc("near Kubadive", expected=6, observed=1, people=5000)
        runner = _loc("near Kwa Pisi", expected=4, observed=3, people=5000)
        summary = _comparison_summary(winner, runner, "salon", rw=False)
        assert summary.startswith("near Kubadive is the stronger pick for a salon")
        assert "more unmet demand" in summary
        assert "near Kwa Pisi" in summary

    def test_fewer_competitors_reason_appears(self):
        winner = _loc("A", expected=5, observed=1, people=5000)
        runner = _loc("B", expected=5, observed=4, people=5000)
        summary = _comparison_summary(winner, runner, "pharmacy", rw=False)
        assert "fewer competitors" in summary

    def test_larger_customer_base_reason_appears(self):
        winner = _loc("A", expected=5, observed=2, people=8000)
        runner = _loc("B", expected=5, observed=2, people=3000)
        summary = _comparison_summary(winner, runner, "cafe", rw=False)
        assert "larger customer base" in summary

    def test_category_underscores_are_humanised(self):
        winner = _loc("A", expected=5, observed=1, people=5000)
        runner = _loc("B", expected=4, observed=3, people=5000)
        summary = _comparison_summary(winner, runner, "fast_food", rw=False)
        assert "fast food" in summary

    def test_falls_back_to_a_generic_reason_when_metrics_are_tied(self):
        winner = _loc("A", expected=5, observed=2, people=5000)
        runner = _loc("B", expected=5, observed=2, people=5000)
        summary = _comparison_summary(winner, runner, "salon", rw=False)
        assert "wider gap" in summary

    def test_kinyarwanda_summary_has_no_english_reasons(self):
        winner = _loc("A", expected=6, observed=1, people=8000)
        runner = _loc("B", expected=4, observed=4, people=3000)
        summary = _comparison_summary(winner, runner, "salon", rw=True)
        assert "stronger pick" not in summary
        assert "ni ho hakwiye kubanza" in summary
