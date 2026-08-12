from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analyzers import analyze_catalog
from app.database import Base
from app.domain import CollectedPriceQuote, CollectedProduct, CollectionStats
from app.models import ScrapeRun, Store
from app.notifications.personal import (
    build_personal_store_ranking_bundle,
    member_priced_saved_items,
)
from app.notifications.policy import SmartAlertContext, build_smart_notification_bundles
from app.repositories.products import save_product


def _member_saved_product():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as session:
        store = Store(
            name="CAV",
            slug="cav",
            base_url="https://cav.cl",
            connector_key="cav",
            is_active=True,
            requires_browser=True,
            comparison_enabled=False,
            diagnostic_mode=False,
            personal_comparison_enabled=True,
        )
        session.add(store)
        session.flush()
        run = ScrapeRun(store_id=store.id, status="running")
        session.add(run)
        session.flush()
        saved = save_product(
            session,
            CollectedProduct(
                store="CAV",
                name="Flor De Cana 18 Anos Centenario 750 ml",
                url="https://cav.cl/tienda/producto/flor-de-cana-18-12345",
                current_price=49990,
                regular_price=None,
                discount_pct=0.0,
                price_quotes=(
                    CollectedPriceQuote(
                        49990,
                        "PUBLIC",
                        audience_key="public",
                        eligibility_required=False,
                    ),
                    CollectedPriceQuote(
                        36000,
                        "MEMBER",
                        regular_price=49990,
                        audience_key="cav_member",
                        eligibility_required=True,
                    ),
                ),
            ),
            store,
            run,
        )
        session.flush()
        # Mantener objetos usables fuera de la sesión para estas pruebas puras.
        session.expunge(saved.product)
        store_id = int(store.id)
        run_id = int(run.id)
    engine.dispose()
    return saved, store_id, run_id


def test_member_projection_uses_cav_member_price_and_normal_reference():
    saved, _, _ = _member_saved_product()
    projected = member_priced_saved_items(
        [saved], eligible_audiences=("cav_member",)
    )
    assert len(projected) == 1
    row = projected[0]
    assert row.item.current_price == 36000
    assert row.item.regular_price == 49990
    assert round(row.item.discount_pct, 4) == round((49990 - 36000) / 49990, 4)
    # Las bajas MEMBER se notifican por el canal personal específico.
    assert row.previous_price is None


def test_cav_ranking_reuses_store_format_with_member_prices():
    saved, store_id, run_id = _member_saved_product()
    projected = member_priced_saved_items(
        [saved], eligible_audiences=("cav_member",)
    )
    bundle = build_personal_store_ranking_bundle(
        store_id=store_id,
        run_id=run_id,
        store_name="CAV",
        member_items=projected,
        report_limit=30,
    )
    assert bundle is not None
    assert bundle.alert_type == "personal_store_ranking"
    assert len(bundle.messages) == 1
    message = bundle.messages[0]
    assert "🏆 Mejores precios 1-1 de 1 · CAV" in message
    assert "Precio actual: $36.000" in message
    assert "Precio normal informado: $49.990" in message
    assert "Descuento informado: 28%" in message
    assert "Ahorro informado: $13.990" in message
    assert "Motivo del ranking: precio socio CAV" in message
    assert "https://cav.cl/tienda/producto/flor-de-cana-18-12345" in message


def test_cav_store_ranking_is_emitted_once_per_successful_run():
    saved, store_id, run_id = _member_saved_product()
    projected = member_priced_saved_items(
        [saved], eligible_audiences=("cav_member",)
    )
    first = build_personal_store_ranking_bundle(
        store_id=store_id,
        run_id=run_id,
        store_name="CAV",
        member_items=projected,
    )
    second = build_personal_store_ranking_bundle(
        store_id=store_id,
        run_id=run_id + 1,
        store_name="CAV",
        member_items=projected,
    )
    assert first is not None and second is not None
    # Mismo ranking, distinto run: la siguiente revisión válida vuelve a enviarlo.
    assert first.payload_hash == second.payload_hash
    assert first.deduplication_key != second.deduplication_key


def test_smart_policy_can_suppress_public_ranking_for_personal_only_source():
    saved, store_id, run_id = _member_saved_product()
    projected = member_priced_saved_items(
        [saved], eligible_audiences=("cav_member",)
    )
    analysis = analyze_catalog(
        projected,
        collection_stats=CollectionStats(
            unique_products=1,
            health_status="HEALTHY",
            health_score=100,
        ),
    )
    bundles = build_smart_notification_bundles(
        items=projected,
        analysis=analysis,
        context=SmartAlertContext(
            store_id=store_id,
            run_id=run_id,
            store_name="CAV",
            previous_health_status="HEALTHY",
            previous_product_count=1,
            min_drop_pct=0.05,
            min_drop_amount=1000,
            digest_interval_hours=24,
            alert_new_products=False,
            alert_price_increases=False,
            max_change_items=10,
            report_limit=30,
        ),
        include_ranking=False,
    )
    assert bundles == []
