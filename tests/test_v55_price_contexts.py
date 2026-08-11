from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.collectors.cav import _parse_html as parse_cav_html
from app.collectors.lavinoteca import _extract_product as extract_lavinoteca_product
from app.database import Base
from app.domain import CollectedPriceQuote, CollectedProduct
from app.intelligence.personal import refresh_personal_opportunities, top_personal_opportunities
from app.models import ProductPriceQuote, ScrapeRun, Store
from app.repositories.products import save_product


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _store(session, *, name, key, comparison_enabled=True, diagnostic_mode=False):
    row = Store(
        name=name,
        slug=key,
        base_url=f"https://{key}.example",
        connector_key=key,
        is_active=True,
        requires_browser=False,
        comparison_enabled=comparison_enabled,
        diagnostic_mode=diagnostic_mode,
    )
    session.add(row)
    session.flush()
    return row


def test_lavinoteca_vtex_extracts_price_sku_ean():
    item = {
        "productName": "Johnnie Walker Black Label 750 ml",
        "link": "https://www.lavinoteca.cl/jw-black/p",
        "items": [{
            "itemId": "4481",
            "ean": "7801234567890",
            "sellers": [{
                "commertialOffer": {
                    "IsAvailable": True,
                    "AvailableQuantity": 12,
                    "Price": 22990.0,
                    "ListPrice": 27990.0,
                }
            }],
        }],
    }
    product = extract_lavinoteca_product(item)
    assert product is not None
    assert product.store == "La Vinoteca"
    assert product.current_price == 22990
    assert product.regular_price == 27990
    assert product.sku == "4481"
    assert product.ean == "7801234567890"
    assert product.price_quotes[0].price_type == "SALE"


def test_cav_parser_separates_member_sale_and_public_prices():
    html = """
    <article class="product-card">
      <a href="/tienda/producto/gin-ejemplo-700cc-32531"><h3>Gin Ejemplo 700cc</h3></a>
      <div>Socio: $18.891</div>
      <div>Oferta: $19.990</div>
      <div>Normal: $20.990</div>
      <div>Stock: 12</div>
    </article>
    """
    products, cards = parse_cav_html(html)
    assert cards == 1
    product = next(iter(products.values()))
    assert product.current_price == 20990  # precio base diagnóstico = normal
    assert product.sku == "32531"
    quotes = {(q.price_type, q.audience_key): q.price for q in product.price_quotes}
    assert quotes[("PUBLIC", "public")] == 20990
    assert quotes[("SALE", "public_offer")] == 19990
    assert quotes[("MEMBER", "cav_member")] == 18891


def test_save_product_persists_contextual_quotes():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        store = _store(session, name="CAV", key="cav", comparison_enabled=False, diagnostic_mode=True)
        run = ScrapeRun(store_id=store.id, status="running")
        session.add(run)
        session.flush()
        save_product(session, CollectedProduct(
            store="CAV",
            name="Whisky Demo 750 ml",
            url="https://cav.example/p/1",
            current_price=20000,
            regular_price=None,
            discount_pct=0,
            price_quotes=(
                CollectedPriceQuote(20000, "PUBLIC", audience_key="public"),
                CollectedPriceQuote(18000, "MEMBER", regular_price=20000, audience_key="cav_member", eligibility_required=True),
            ),
        ), store, run)
        session.flush()
        rows = list(session.scalars(select(ProductPriceQuote).order_by(ProductPriceQuote.price)))
        assert [(row.price_type, row.price) for row in rows] == [("MEMBER", 18000), ("PUBLIC", 20000)]
        assert rows[0].eligibility_required is True
    engine.dispose()


def test_personal_preview_can_use_cav_without_changing_public_store_flag():
    engine, SessionLocal = _session_factory()
    with SessionLocal() as session:
        public = _store(session, name="La Vinoteca", key="lavinoteca")
        cav = _store(session, name="CAV", key="cav", comparison_enabled=False, diagnostic_mode=True)
        run_public = ScrapeRun(store_id=public.id, status="running")
        run_cav = ScrapeRun(store_id=cav.id, status="running")
        session.add_all([run_public, run_cav])
        session.flush()
        a = save_product(session, CollectedProduct(
            store="La Vinoteca", name="Whisky Demo 750 ml", url="https://lavinoteca.example/demo",
            current_price=24000, regular_price=None, discount_pct=0,
        ), public, run_public)
        b = save_product(session, CollectedProduct(
            store="CAV", name="Whisky Demo 750 ml", url="https://cav.example/demo",
            current_price=26000, regular_price=None, discount_pct=0,
            price_quotes=(
                CollectedPriceQuote(26000, "PUBLIC", audience_key="public"),
                CollectedPriceQuote(21000, "MEMBER", regular_price=26000, audience_key="cav_member", eligibility_required=True),
            ),
        ), cav, run_cav)
        # normalized exact linking already points both publications to the same master.
        assert a.product.master_product_id == b.product.master_product_id
        count = refresh_personal_opportunities(session)
        session.flush()
        views = top_personal_opportunities(session)
        assert count == 1
        assert views[0].winner_store == "CAV"
        assert views[0].winner_price == 21000
        assert views[0].price_type == "MEMBER"
        assert cav.comparison_enabled is False
    engine.dispose()


def test_cav_registry_is_diagnostic_and_lavinoteca_is_public():
    from app.collectors.registry import enabled_collectors
    by_key = {collector.key: collector for collector in enabled_collectors()}
    assert by_key["lavinoteca"].metadata.comparison_enabled is True
    assert by_key["lavinoteca"].metadata.diagnostic_mode is False
    assert by_key["cav"].metadata.comparison_enabled is False
    assert by_key["cav"].metadata.diagnostic_mode is True


def test_personal_command_aliases():
    from app.telegram_bot.commands import parse_command
    assert parse_command("/personal").name == "personal_opportunities"
    assert parse_command("/miprecio").name == "personal_opportunities"
