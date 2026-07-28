from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.favorites import (
    add_or_update_favorite,
    deactivate_favorite,
    deliver_pending_favorite_alerts,
    evaluate_favorite_alerts,
    list_favorites,
)
from app.models import (
    FavoriteAlert,
    MasterProduct,
    PriceObservation,
    Product,
    ScrapeRun,
    Store,
    TelegramFavorite,
)
from app.search.engine import SearchOffer, SearchResult
from app.telegram_bot.commands import parse_command


def _database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _search_result(master_id: int) -> SearchResult:
    now = datetime.now(timezone.utc)
    first = SearchOffer(
        product_id=1,
        store_name="Líquidos",
        product_name="Johnnie Walker Black 750 ml",
        price=21990,
        regular_price=25990,
        discount_pct=0.15,
        url="https://example.com/liquidos",
        last_seen_at=now,
    )
    second = SearchOffer(
        product_id=2,
        store_name="Licor3B",
        product_name="Johnnie Walker Black 750 ml",
        price=24990,
        regular_price=None,
        discount_pct=0,
        url="https://example.com/licor3b",
        last_seen_at=now,
    )
    return SearchResult(
        master_product_id=master_id,
        canonical_name="Johnnie Walker Black 750 ml",
        brand="Johnnie Walker",
        variant="Black",
        volume_ml=750,
        package_quantity=1,
        score=0.97,
        offers=(first, second),
        winner=first,
        runner_up=second,
        saving_clp=3000,
        saving_pct=3000 / 24990,
    )


def test_favorite_commands_parse_chilean_prices():
    assert parse_command("/favorito johnnie black 750").name == "favorite_add"
    target = parse_command("/avisar johnnie black 750 bajo $25.000")
    assert target.name == "favorite_target"
    assert target.query == "johnnie black 750"
    assert target.value == 25000
    assert parse_command("/misfavoritos").name == "favorite_list"
    delete = parse_command("/eliminarfavorito 12")
    assert delete.name == "favorite_delete"
    assert delete.value == 12


def test_add_list_and_deactivate_favorite():
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
        favorite, created = add_or_update_favorite(
            session,
            chat_id=123,
            result=_search_result(int(master.id)),
            target_price=23000,
        )
        session.commit()
        favorite_id = int(favorite.id)
        assert created is True

    with Session() as session:
        views = list_favorites(session, chat_id=123)
        assert len(views) == 1
        assert views[0].favorite_id == favorite_id
        assert views[0].target_price == 23000
        assert deactivate_favorite(session, chat_id=123, favorite_id=favorite_id)
        session.commit()

    with Session() as session:
        assert list_favorites(session, chat_id=123) == []
    engine.dispose()


def test_evaluator_combines_price_target_and_winner_events_and_delivers():
    engine, Session = _database()
    now = datetime.now(timezone.utc)
    with Session() as session:
        store_a = Store(
            name="Licor3B",
            slug="licor3b",
            base_url="https://licor3b.cl",
            connector_key="licor3b",
        )
        store_b = Store(
            name="Líquidos",
            slug="liquidos",
            base_url="https://liquidos.cl",
            connector_key="liquidos",
        )
        master = MasterProduct(
            canonical_name="Johnnie Walker Black 750 ml",
            normalized_key="johnnie walker black|750",
            volume_ml=750,
            package_quantity=1,
            status="active",
        )
        session.add_all([store_a, store_b, master])
        session.flush()
        run_a = ScrapeRun(store_id=store_a.id, status="success")
        run_b = ScrapeRun(store_id=store_b.id, status="success")
        session.add_all([run_a, run_b])
        session.flush()
        product_a = Product(
            store="Licor3B",
            store_id=store_a.id,
            master_product_id=master.id,
            name=master.canonical_name,
            url="https://example.com/a",
            current_price=24000,
            last_seen_at=now,
        )
        product_b = Product(
            store="Líquidos",
            store_id=store_b.id,
            master_product_id=master.id,
            name=master.canonical_name,
            url="https://example.com/b",
            current_price=22000,
            last_seen_at=now,
        )
        session.add_all([product_a, product_b])
        session.flush()
        session.add_all(
            [
                PriceObservation(
                    product_id=product_a.id,
                    scrape_run_id=run_a.id,
                    price=24000,
                ),
                PriceObservation(
                    product_id=product_b.id,
                    scrape_run_id=run_b.id,
                    price=22000,
                ),
            ]
        )
        favorite = TelegramFavorite(
            chat_id=123,
            master_product_id=master.id,
            target_price=23000,
            last_best_price=25000,
            last_winner_store="Licor3B",
            last_store_names=["Licor3B", "Líquidos"],
            was_available=True,
            last_evaluated_at=now,
            is_active=True,
        )
        session.add(favorite)
        session.commit()
        run_ids = (int(run_a.id), int(run_b.id))

    with Session() as session:
        evaluated, queued = evaluate_favorite_alerts(
            session,
            run_ids=run_ids,
            coverage_complete=True,
            minimum_drop_clp=1,
        )
        session.commit()
        assert evaluated == 1
        assert queued == 1
        alert = session.scalar(select(FavoriteAlert))
        assert alert is not None
        assert set(alert.event_types) == {"price_drop", "target_reached", "winner_change"}
        assert "$22.000" in alert.message

    sent_messages = []

    def fake_send(token: str, chat_id: str, message: str) -> None:
        sent_messages.append((token, chat_id, message))

    sent, failed = deliver_pending_favorite_alerts(
        SessionLocal=Session,
        telegram_bot_token="token",
        send_message_fn=fake_send,
    )
    assert (sent, failed) == (1, 0)
    assert sent_messages[0][1] == "123"

    with Session() as session:
        alert = session.scalar(select(FavoriteAlert))
        assert alert is not None and alert.status == "sent"
    engine.dispose()
