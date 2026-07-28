from app.matching.cross_store import build_product_signature


def test_gift_and_personalized_products_are_not_cross_store_comparable():
    assert build_product_signature("Gin Kantal 750cc + Copa Original").is_pack
    assert build_product_signature("Whisky Black Label 750cc Personalizado").is_pack
    assert build_product_signature("Gin Beefeater 750cc con vaso de regalo").is_pack
    assert not build_product_signature("Gin Bombay Sapphire 750cc").is_pack
