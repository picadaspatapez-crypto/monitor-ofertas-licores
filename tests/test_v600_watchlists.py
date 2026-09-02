from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.favorites import (
    configure_watchlist,
    evaluate_favorite_alerts,
    list_watchlists,
)
from app.models import (
    FavoriteAlert,
    MasterProduct,
    OpportunitySnapshot,
    PersonalOpportunitySnapshot,
    PriceObservation,
    Product,
    ScrapeRun,
    Store,
    TelegramFavorite,
)
from app.search.engine import SearchOffer, SearchResult
from app.telegram_bot.commands import parse_command
from app.telegram_bot.formatting import format_watchlists_list


def _database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _result(master_id: int, *, price: int = 21990) -> SearchResult:
    now = datetime.now(timezone.utc)
    offer = SearchOffer(
        product_id=1,
        store_name="Líquidos",
        product_name="Johnnie Walker Black 750 ml",
        price=price,
        regular_price=25990,
        discount_pct=0.15,
        url="https://example.com/black",
        last_seen_at=now,
    )
    return SearchResult(
        master_product_id=master_id,
        canonical_name="Johnnie Walker Black 750 ml",
        brand="Johnnie Walker",
        variant="Black",
        volume_ml=750,
        package_quantity=1,
        score=0.98,
        offers=(offer,),
        winner=offer,
        runner_up=None,
        saving_clp=0,
        saving_pct=0.0,
    )


def _seed_current(session, *, price: int = 22000):
    now = datetime.now(timezone.utc)
    store = Store(
        name="Líquidos",
        slug="liquidos",
        base_url="https://example.com",
        connector_key="liquidos",
    )
    master = MasterProduct(
        canonical_name="Johnnie Walker Black 750 ml",
        normalized_key="johnnie walker black|750",
        volume_ml=750,
        package_quantity=1,
        status="active",
    )
    session.add_all([store, master])
    session.flush()
    run = ScrapeRun(store_id=store.id, status="success")
    session.add(run)
    session.flush()
    product = Product(
        store=store.name,
        store_id=store.id,
        master_product_id=master.id,
        name=master.canonical_name,
        url="https://example.com/black",
        current_price=price,
        last_seen_at=now,
    )
    session.add(product)
    session.flush()
    session.add(
        PriceObservation(
            product_id=product.id,
            scrape_run_id=run.id,
            price=price,
        )
    )
    session.flush()
    return store, master, product, run


def test_watchlist_command_parser_supports_four_v600_rules():
    target = parse_command("/vigilar johnnie black 750 bajo $25.000")
    assert (target.name, target.query, target.value) == (
        "watch_target",
        "johnnie black 750",
        25000,
    )

    score = parse_command("/vigilar johnnie black 750 score 90")
    assert (score.name, score.query, score.value) == (
        "watch_score",
        "johnnie black 750",
        90,
    )

    historical = parse_command("/vigilar johnnie black 750 nuevo mínimo histórico")
    assert historical.name == "watch_historical_min"
    assert historical.query == "johnnie black 750"

    cav = parse_command("/vigilar johnnie black 750 cav ventaja $3.000")
    assert (cav.name, cav.query, cav.value) == (
        "watch_cav",
        "johnnie black 750",
        3000,
    )

    assert parse_command("/watchlist").name == "watch_list"
    assert parse_command("/quitarwatch 7").value == 7


def test_configure_watchlist_reuses_favorite_and_initializes_state_without_chatter():
    engine, Session = _database()
    with Session() as session:
        master = MasterProduct(
            canonical_name="Johnnie Walker Black 750 ml",
            normalized_key="johnnie walker black|750",
            volume_ml=750,
            package_quantity=1,
            status="active",
        )
        session.add(master)
        session.flush()
        session.add(
            OpportunitySnapshot(
                master_product_id=master.id,
                score=92.0,
                classification="Excelente",
                winner_price=21990,
            )
        )
        session.flush()

        favorite, created = configure_watchlist(
            session,
            chat_id=123,
            result=_result(int(master.id)),
            rule="target",
            value=23000,
        )
        assert created is True
        assert favorite.target_price == 23000
        assert favorite.watch_state["target_met"] is True
        assert favorite.notify_on_price_drop is False
        assert favorite.notify_on_new_store is False

        same, created_again = configure_watchlist(
            session,
            chat_id=123,
            result=_result(int(master.id)),
            rule="score",
            value=90,
        )
        session.commit()
        assert created_again is False
        assert same.id == favorite.id
        assert same.target_price == 23000
        assert same.min_opportunity_score == 90.0
        assert same.watch_state["score_met"] is True

    engine.dispose()


def test_watchlist_list_exposes_live_conditions_and_formatter():
    engine, Session = _database()
    with Session() as session:
        _store, master, _product, _run = _seed_current(session, price=22000)
        session.add(
            OpportunitySnapshot(
                master_product_id=master.id,
                score=91.0,
                classification="Excelente",
                winner_price=22000,
                price_event="AT_HISTORICAL_MIN",
            )
        )
        session.add(
            PersonalOpportunitySnapshot(
                master_product_id=master.id,
                score=90.0,
                classification="Excelente",
                winner_price=20000,
                winner_price_type="MEMBER",
                winner_audience_key="cav_member",
                personal_advantage_clp=4000,
                public_reference_price=24000,
            )
        )
        session.add(
            TelegramFavorite(
                chat_id=123,
                master_product_id=master.id,
                target_price=23000,
                min_opportunity_score=90,
                notify_on_new_historical_min=True,
                min_personal_advantage_clp=3000,
                is_active=True,
            )
        )
        session.commit()

        views = list_watchlists(session, chat_id=123)
        assert len(views) == 1
        view = views[0]
        assert view.opportunity_score == 91.0
        assert view.personal_advantage_clp == 4000
        text = format_watchlists_list(views)
        assert "Score ≥ 90.0" in text
        assert "CAV ≥ $3.000" in text
        assert "alcanzado" in text

    engine.dispose()


def test_score_watch_fires_only_on_false_to_true_transition():
    engine, Session = _database()
    with Session() as session:
        _store, master, _product, run = _seed_current(session)
        session.add(
            OpportunitySnapshot(
                master_product_id=master.id,
                score=92.0,
                classification="Excelente",
                winner_price=22000,
            )
        )
        session.add(
            TelegramFavorite(
                chat_id=123,
                master_product_id=master.id,
                min_opportunity_score=90,
                watch_state={"score_met": False},
                notify_on_price_drop=False,
                notify_on_new_store=False,
                notify_on_winner_change=False,
                notify_on_back_in_stock=False,
                is_active=True,
            )
        )
        session.commit()
        run_id = int(run.id)

    with Session() as session:
        evaluated, queued = evaluate_favorite_alerts(
            session,
            run_ids=(run_id,),
            coverage_complete=True,
        )
        session.commit()
        assert (evaluated, queued) == (1, 1)
        alert = session.scalar(select(FavoriteAlert))
        assert alert is not None
        assert alert.event_types == ["opportunity_score_reached"]

    with Session() as session:
        evaluated, queued = evaluate_favorite_alerts(
            session,
            run_ids=(run_id,),
            coverage_complete=True,
        )
        session.commit()
        assert (evaluated, queued) == (1, 0)

    engine.dispose()


def test_historical_min_watch_deduplicates_same_minimum_but_allows_a_new_lower_minimum():
    engine, Session = _database()
    with Session() as session:
        _store, master, _product, run = _seed_current(session, price=21000)
        opportunity = OpportunitySnapshot(
            master_product_id=master.id,
            score=95.0,
            classification="Excelente",
            winner_price=21000,
            previous_historical_min=22000,
            price_event="NEW_HISTORICAL_MIN",
        )
        session.add(opportunity)
        session.add(
            TelegramFavorite(
                chat_id=123,
                master_product_id=master.id,
                notify_on_new_historical_min=True,
                watch_state={},
                notify_on_price_drop=False,
                notify_on_new_store=False,
                notify_on_winner_change=False,
                notify_on_back_in_stock=False,
                is_active=True,
            )
        )
        session.commit()
        run_id = int(run.id)

    with Session() as session:
        assert evaluate_favorite_alerts(
            session, run_ids=(run_id,), coverage_complete=True
        ) == (1, 1)
        session.commit()

    with Session() as session:
        assert evaluate_favorite_alerts(
            session, run_ids=(run_id,), coverage_complete=True
        ) == (1, 0)
        opportunity = session.get(OpportunitySnapshot, 1)
        opportunity.winner_price = 20000
        opportunity.previous_historical_min = 21000
        opportunity.price_event = "NEW_HISTORICAL_MIN"
        session.commit()

    with Session() as session:
        assert evaluate_favorite_alerts(
            session, run_ids=(run_id,), coverage_complete=True
        ) == (1, 1)
        session.commit()
        alerts = list(session.scalars(select(FavoriteAlert).order_by(FavoriteAlert.id)))
        assert len(alerts) == 2
        assert all("new_historical_min" in alert.event_types for alert in alerts)

    engine.dispose()


def test_cav_advantage_watch_requires_cav_and_threshold_transition():
    engine, Session = _database()
    with Session() as session:
        _store, master, _product, run = _seed_current(session, price=24000)
        session.add(
            PersonalOpportunitySnapshot(
                master_product_id=master.id,
                score=93.0,
                classification="Excelente",
                winner_price=20000,
                winner_price_type="MEMBER",
                winner_audience_key="cav_member",
                personal_advantage_clp=4000,
                public_reference_price=24000,
            )
        )
        session.add(
            TelegramFavorite(
                chat_id=123,
                master_product_id=master.id,
                min_personal_advantage_clp=3000,
                watch_state={"cav_advantage_met": False},
                notify_on_price_drop=False,
                notify_on_new_store=False,
                notify_on_winner_change=False,
                notify_on_back_in_stock=False,
                is_active=True,
            )
        )
        session.commit()
        run_id = int(run.id)

    with Session() as session:
        assert evaluate_favorite_alerts(
            session, run_ids=(run_id,), coverage_complete=True
        ) == (1, 1)
        session.commit()
        alert = session.scalar(select(FavoriteAlert))
        assert alert is not None
        assert alert.event_types == ["cav_advantage_reached"]
        assert "$4.000" in alert.message

    with Session() as session:
        personal = session.get(PersonalOpportunitySnapshot, 1)
        personal.winner_audience_key = "public"
        session.commit()
        assert evaluate_favorite_alerts(
            session, run_ids=(run_id,), coverage_complete=True
        ) == (1, 0)
        session.commit()
        favorite = session.scalar(select(TelegramFavorite))
        assert favorite.watch_state["cav_advantage_met"] is False

    engine.dispose()


def test_watchlist_migration_is_chained_after_commercial_intelligence():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0013_watchlists.py"
    source = path.read_text()
    assert 'revision = "0013_watchlists"' in source
    assert 'down_revision = "0012_commercial_intelligence"' in source
    assert '"min_opportunity_score"' in source
    assert '"watch_state"' in source
