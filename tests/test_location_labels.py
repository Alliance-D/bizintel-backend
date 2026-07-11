from app.services.location_labels import location_label


def test_cell_and_sector_present():
    assert location_label("Gasabo", "Kimironko", "Bibare", None) == "Bibare, Kimironko"


def test_cell_equal_to_sector_is_collapsed():
    assert location_label("Gasabo", "Kimironko", "Kimironko", None) == "Kimironko"


def test_village_is_ignored():
    # villages are deliberately not used in labels; cell+sector is what shows
    label = location_label("Nyarugenge", "Nyarugenge", "Kiyovu", "Ingenzi")
    assert label == "Kiyovu, Nyarugenge"
    assert "Ingenzi" not in label


def test_cell_only():
    assert location_label(None, None, "Bibare", None) == "Bibare"


def test_sector_and_district_when_cell_missing():
    assert location_label("Gasabo", "Kimironko", None, None) == "Kimironko, Gasabo"


def test_sector_equal_to_district_is_collapsed():
    assert location_label("Nyarugenge", "Nyarugenge", None, None) == "Nyarugenge"


def test_district_only():
    assert location_label("Gasabo", None, None, None) == "Gasabo"


def test_nothing_present_falls_back_to_kigali():
    assert location_label(None, None, None, None) == "Kigali"
