from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analyzers import analyze_cross_store_prices
from app.database import Base
from app.domain import CollectedProduct
from app.models import ScrapeRun, Store
from app.repositories import reconcile_cross_store_matches, save_product


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _store(name: str, slug: str) -> Store:
    return Store(
        name=name,
        slug=slug,
        base_url=f"https://{slug}.example",
        connector_key=slug,
        requires_browser=True,
    )


def test_reconcile_and_compare_prices_between_stores():
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        licor3b = _store("Licor3B", "licor3b")
        liquidos = _store("Líquidos", "liquidos")
        session.add_all([licor3b, liquidos])
        session.flush()
        run_a = ScrapeRun(store=licor3b, status="running")
        run_b = ScrapeRun(store=liquidos, status="running")
        session.add_all([run_a, run_b])
        session.flush()
        save_product(
            session,
            CollectedProduct(
                store="Licor3B",
                name="Whisky Johnnie Walker Black Label 750 ml",
                url="https://licor3b.example/black",
                current_price=24990,
                regular_price=29990,
                discount_pct=0.17,
            ),
            licor3b,
            run_a,
        )
        save_product(
            session,
            CollectedProduct(
                store="Líquidos",
                name="Johnnie Walker Etiqueta Negra 75 cl",
                url="https://liquidos.example/black",
                current_price=21990,
                regular_price=27990,
                discount_pct=0.21,
            ),
            liquidos,
            run_b,
        )
        session.flush()
        summary = reconcile_cross_store_matches(
            session,
            run_ids=[run_a.id, run_b.id],
        )
        analysis = analyze_cross_store_prices(
            session,
            run_ids=[run_a.id, run_b.id],
        )
        session.commit()

    assert summary.matched_pairs == 1
    assert analysis.verified_matches == 1
    assert len(analysis.opportunities) == 1
    opportunity = analysis.opportunities[0]
    assert opportunity.winner.store_name == "Líquidos"
    assert opportunity.saving_clp == 3000


def test_pack_is_not_compared_with_single_bottle():
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        a = _store("A", "a")
        b = _store("B", "b")
        session.add_all([a, b])
        session.flush()
        run_a = ScrapeRun(store=a, status="running")
        run_b = ScrapeRun(store=b, status="running")
        session.add_all([run_a, run_b])
        session.flush()
        save_product(
            session,
            CollectedProduct("A", "Pack 6 Cerveza X 330 ml", "https://a/p", 6000, None, 0),
            a,
            run_a,
        )
        save_product(
            session,
            CollectedProduct("B", "Cerveza X 330 ml", "https://b/p", 1200, None, 0),
            b,
            run_b,
        )
        summary = reconcile_cross_store_matches(session, run_ids=[run_a.id, run_b.id])
        analysis = analyze_cross_store_prices(session, run_ids=[run_a.id, run_b.id])
    assert summary.skipped_packs == 1
    assert analysis.verified_matches == 0
