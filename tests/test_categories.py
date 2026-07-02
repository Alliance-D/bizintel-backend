from app.core.categories import BUSINESS_CATEGORIES, normalise_category


def test_normalise_category_passes_through_known_key():
    assert normalise_category("salon") == "salon"


def test_normalise_category_resolves_aliases():
    assert normalise_category("barbershop") == "salon"
    assert normalise_category("Fast-Food") == "restaurant"
    assert normalise_category("SUPERMARKET") == "grocery"


def test_normalise_category_falls_back_to_pharmacy_for_unknown_input():
    assert normalise_category("totally-unknown-category") == "pharmacy"
    assert normalise_category(None) == "pharmacy"
    assert normalise_category("") == "pharmacy"


def test_every_active_category_has_weights_that_sum_close_to_one():
    for category in BUSINESS_CATEGORIES:
        total = sum(category.weights.values())
        assert 0.98 <= total <= 1.02, f"{category.key} weights sum to {total}, expected ~1.0"
