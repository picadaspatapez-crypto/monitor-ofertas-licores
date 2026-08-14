from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.intelligence.canonical import canonical_fingerprint, refresh_canonical_catalog
from app.intelligence.quality import assess_product_quality, extract_abv_pct, extract_vintage_year
from app.matching import build_matching_plan, build_product_signature, compare_signatures
from app.matching.review import resolve_review
from app.models import MatchingReview, MatchingRule, MasterProduct, Product, Store


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_quality_blocks_null_product_name():
    result = assess_product_quality(
        name="Null", url="https://example.com/null", current_price=2600,
        regular_price=9990, discount_pct=0.74,
    )
    assert result.status == "BLOCKED"
    assert result.excluded_from_comparison is True
    assert "invalid_name" in result.issues


def test_quality_blocks_extreme_price_jump_for_one_cycle():
    result = assess_product_quality(
        name="Johnnie Walker Black Label 750 ml",
        url="https://example.com/jw",
        current_price=2990,
        regular_price=39990,
        discount_pct=0.92,
        previous_price=29990,
    )
    assert result.status == "BLOCKED"
    assert "extreme_price_jump" in result.issues


def test_identity_extracts_abv_and_vintage():
    name = "Cabernet Reserva 2022 14% alc. 750 ml"
    assert extract_abv_pct(name) == 14.0
    assert extract_vintage_year(name) == 2022


def test_matching_rejects_different_vintages():
    left = build_product_signature("Vino Ejemplo Reserva 2021 750 ml")
    right = build_product_signature("Vino Ejemplo Reserva 2022 750 ml")
    score = compare_signatures(left, right)
    assert score.accepted is False
    assert score.method == "vintage_conflict"


def test_matching_rejects_incompatible_abv():
    left = build_product_signature("Gin Ejemplo 40° 700 ml")
    right = build_product_signature("Gin Ejemplo 47° 700 ml")
    score = compare_signatures(left, right)
    assert score.accepted is False
    assert score.method == "abv_conflict"


@dataclass
class _CandidateProduct:
    id: int
    store_id: int
    name: str


def test_matching_plan_routes_near_threshold_pair_to_review_queue():
    products = [
        _CandidateProduct(1, 1, "Johnnie Walker Black Label 750 ml"),
        _CandidateProduct(2, 2, "Johnnie Walker Black Edition 750 ml"),
    ]
    plan = build_matching_plan(products, minimum_confidence=0.80)
    assert plan.candidates == ()
    assert len(plan.review_candidates) == 1
    assert 0.72 <= plan.review_candidates[0].confidence < 0.80


def test_manual_review_rejection_creates_persistent_exclusion_rule():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        left_store = Store(name="A", slug="a", base_url="https://a.example", connector_key="a")
        right_store = Store(name="B", slug="b", base_url="https://b.example", connector_key="b")
        session.add_all([left_store, right_store]); session.flush()
        left = Product(store="A", store_id=left_store.id, name="Whisky Alpha 750 ml", url="https://a.example/a", current_price=10000)
        right = Product(store="B", store_id=right_store.id, name="Whisky Alfa 750 ml", url="https://b.example/b", current_price=11000)
        session.add_all([left, right]); session.flush()
        review = MatchingReview(left_product_id=left.id, right_product_id=right.id, confidence=.82, proposed_method="near_threshold", status="pending")
        session.add(review); session.flush()
        resolve_review(session, review_id=review.id, decision="reject", notes="productos distintos")
        session.commit()
        assert review.status == "rejected"
        rule = session.scalar(select(MatchingRule).where(MatchingRule.rule_type == "exclusion"))
        assert rule is not None and rule.is_active
    engine.dispose()


def test_canonical_refresh_registers_identity_metadata_and_aliases():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        store = Store(name="A", slug="a", base_url="https://a.example", connector_key="a")
        master = MasterProduct(canonical_name="Example", normalized_key="example|750")
        session.add_all([store, master]); session.flush()
        product = Product(
            store="A", store_id=store.id, master_product_id=master.id,
            name="Example Reserva 2022 14° 750 ml", url="https://a.example/x",
            current_price=9990, data_quality_score=95,
        )
        session.add(product); session.flush()
        summary = refresh_canonical_catalog(session, master_ids={master.id})
        assert summary.masters_updated == 1
        assert master.vintage_year == 2022
        assert master.abv_pct == 14.0
        assert master.canonical_fingerprint == canonical_fingerprint(product.name)
        assert master.package_quantity == 1
    engine.dispose()


def test_store_ranking_never_includes_quality_blocked_items():
    from app.domain import CollectedProduct, SavedProduct
    from app.reports.telegram import ranked_best_prices

    good_product = Product(store="A", name="Whisky Bueno 750 ml", url="https://a.example/g", current_price=10000)
    good_product.id = 1
    good_product.excluded_from_comparison = False
    bad_product = Product(store="A", name="Null", url="https://a.example/null", current_price=2600)
    bad_product.id = 2
    bad_product.excluded_from_comparison = True
    good = SavedProduct(
        item=CollectedProduct(store="A", name=good_product.name, url=good_product.url, current_price=10000, regular_price=20000, discount_pct=.5),
        product=good_product, is_new=False, previous_price=12000,
    )
    bad = SavedProduct(
        item=CollectedProduct(store="A", name=bad_product.name, url=bad_product.url, current_price=2600, regular_price=9990, discount_pct=.74),
        product=bad_product, is_new=True, previous_price=None,
    )
    ranked = ranked_best_prices([bad, good])
    assert [item.item.name for item in ranked] == ["Whisky Bueno 750 ml"]
