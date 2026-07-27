from app.matching import extract_volume_ml, normalize_product_name


def test_volume_units():
    assert extract_volume_ml("750 cc") == 750
    assert extract_volume_ml("75 cl") == 750
    assert extract_volume_ml("1 litro") == 1000


def test_equivalent_names_share_key():
    a = normalize_product_name("Whisky Johnnie Walker Black 750 ml")
    b = normalize_product_name("Johnnie Walker Black 75 cl")
    assert a.normalized_key == b.normalized_key
