from app.services.location_labels import location_label


def test_village_and_sector_present():
    label = location_label("Nyarugenge", "Nyarugenge", "Kiyovu", "Ingenzi")
    assert "Ingenzi" in label and "Nyarugenge" in label


def test_village_present_but_sector_missing_falls_back_to_district():
    label = location_label("Gasabo", None, "Kimihurura", "Ituze")
    assert "Ituze" in label and "Gasabo" in label


def test_village_only():
    label = location_label(None, None, None, "Ituze")
    assert label == "near Ituze village"


def test_cell_and_sector_when_village_missing():
    label = location_label("Gasabo", "Kimihurura", "Kamukina", None)
    assert label == "Kamukina, Kimihurura sector"


def test_sector_and_district_when_cell_missing():
    label = location_label("Gasabo", "Kimihurura", None, None)
    assert label == "Kimihurura sector, Gasabo district"


def test_district_only():
    assert location_label("Gasabo", None, None, None) == "Gasabo district"


def test_nothing_present_falls_back_to_kigali():
    assert location_label(None, None, None, None) == "Kigali"


def test_kinyarwanda_locale_produces_rw_phrasing():
    label = location_label("Nyarugenge", "Nyarugenge", "Kiyovu", "Ingenzi", locale="rw")
    assert "Murenge" in label and "umudugudu" in label
    assert "Ingenzi" in label
