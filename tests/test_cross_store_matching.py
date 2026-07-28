from types import SimpleNamespace

from app.matching import (
    build_matching_plan,
    build_product_signature,
    compare_signatures,
    extract_pack_count,
)


def test_alias_and_equivalent_volume_match():
    left = build_product_signature("Whisky Johnnie Walker Black Label 750 ml")
    right = build_product_signature("Johnnie Walker Etiqueta Negra 75 cl")
    score = compare_signatures(left, right)
    assert score.accepted
    assert score.confidence >= 0.86
    assert left.volume_ml == right.volume_ml == 750


def test_different_volume_is_rejected():
    left = build_product_signature("Johnnie Walker Black Label 750 ml")
    right = build_product_signature("Johnnie Walker Black Label 1 litro")
    score = compare_signatures(left, right)
    assert not score.accepted
    assert score.method == "volume_conflict"


def test_different_variant_is_rejected():
    left = build_product_signature("Johnnie Walker Black Label 750 ml")
    right = build_product_signature("Johnnie Walker Red Label 750 ml")
    score = compare_signatures(left, right)
    assert not score.accepted
    assert score.method == "variant_conflict"


def test_packs_are_excluded():
    assert extract_pack_count("Pack 6 cervezas 330 ml") == 6
    left = build_product_signature("Pack 6 Johnnie Walker Black 750 ml")
    right = build_product_signature("Johnnie Walker Black 750 ml")
    assert not compare_signatures(left, right).accepted


def test_matching_plan_uses_reciprocal_best_match():
    products = [
        SimpleNamespace(id=1, store_id=1, name="Johnnie Walker Black Label 750 ml"),
        SimpleNamespace(id=2, store_id=2, name="Johnnie Walker Etiqueta Negra 75 cl"),
        SimpleNamespace(id=3, store_id=2, name="Johnnie Walker Red Label 750 ml"),
    ]
    plan = build_matching_plan(products)
    assert [(item.left_id, item.right_id) for item in plan.candidates] == [(1, 2)]


def test_optional_label_word_does_not_block_same_variant():
    left = build_product_signature("Johnnie Walker Black 750 ml")
    right = build_product_signature("Johnnie Walker Black Label 750 ml")
    assert compare_signatures(left, right).accepted


def test_exact_product_can_match_across_four_stores():
    from types import SimpleNamespace
    from app.matching.cross_store import build_matching_plan

    products = [
        SimpleNamespace(id=1, store_id=1, name="Whisky Johnnie Walker Black Label 750 ml"),
        SimpleNamespace(id=2, store_id=2, name="Johnnie Walker Black Label 750cc"),
        SimpleNamespace(id=3, store_id=3, name="Whisky Johnnie Walker Etiqueta Negra 75cl"),
        SimpleNamespace(id=4, store_id=4, name="JW Black Label 0,75 L"),
    ]
    plan = build_matching_plan(products, minimum_confidence=0.86)
    assert plan.ambiguous_products == 0
    assert len(plan.candidates) >= 3
    connected_ids = {
        product_id
        for candidate in plan.candidates
        for product_id in (candidate.left_id, candidate.right_id)
    }
    assert connected_ids == {1, 2, 3, 4}
