from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import MasterProduct, Product, Store
from app.search.engine import SearchOffer, SearchResult
from app.telegram_bot.commands import parse_command
from app.telegram_bot.config import TelegramBotSettings
from app.telegram_bot.formatting import format_search_results
from app.telegram_bot.state import load_next_update_id, save_next_update_id
from app.telegram_bot.worker import TelegramSearchBot


def test_command_parser_accepts_plain_text_and_bot_mentions():
    assert parse_command("johnnie black 750").name == "search"
    assert parse_command("johnnie black 750").query == "johnnie black 750"
    assert parse_command("/buscar@MiBot jack honey").query == "jack honey"
    assert parse_command("/buscar").name == "search_help"
    assert parse_command("/estado").name == "status"
    assert parse_command("/start").name == "help"


def test_bot_settings_fall_back_to_existing_chat_id(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    settings = TelegramBotSettings.from_env()
    assert settings.enabled is True
    assert settings.allowed_chat_ids == frozenset({12345})
    assert settings.result_limit == 5


def test_bot_settings_accept_multiple_authorized_chats(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "123, -456; 789")
    settings = TelegramBotSettings.from_env()
    assert settings.allowed_chat_ids == frozenset({123, -456, 789})


def test_offset_is_persisted():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        assert load_next_update_id(session) is None
        save_next_update_id(session, 42)
        session.commit()
    with Session() as session:
        assert load_next_update_id(session) == 42
    engine.dispose()


def test_telegram_result_formatter_escapes_names_and_builds_buttons():
    now = datetime.now(timezone.utc)
    offer_a = SearchOffer(
        product_id=1,
        store_name="Líquidos & Más",
        product_name="Whisky <Black>",
        price=21990,
        regular_price=25990,
        discount_pct=0.15,
        url="https://example.com/a",
        last_seen_at=now,
    )
    offer_b = SearchOffer(
        product_id=2,
        store_name="Licor3B",
        product_name="Black",
        price=24990,
        regular_price=None,
        discount_pct=0,
        url="https://example.com/b",
        last_seen_at=now,
    )
    result = SearchResult(
        master_product_id=1,
        canonical_name="Johnnie <Walker> Black",
        brand="Johnnie Walker",
        variant="Black",
        volume_ml=750,
        package_quantity=1,
        score=0.96,
        offers=(offer_a, offer_b),
        winner=offer_a,
        runner_up=offer_b,
        saving_clp=3000,
        saving_pct=3000 / 24990,
    )
    text, markup = format_search_results("black <750>", [result])
    assert "&lt;Walker&gt;" in text
    assert "&lt;750&gt;" in text
    assert "$21.990" in text
    assert markup is not None
    buttons = markup["inline_keyboard"][0]
    assert buttons[0]["url"] == "https://example.com/a"


def test_telegram_result_formatter_builds_buttons_for_four_stores():
    now = datetime.now(timezone.utc)
    offers = tuple(
        SearchOffer(
            product_id=index,
            store_name=store,
            product_name="Producto 750 ml",
            price=20_000 + index * 1_000,
            regular_price=None,
            discount_pct=0,
            url=f"https://example.com/{index}",
            last_seen_at=now,
        )
        for index, store in enumerate(
            ("Tost", "GradoÚnico", "Líquidos", "Licor3B"), start=1
        )
    )
    result = SearchResult(
        master_product_id=9,
        canonical_name="Producto 750 ml",
        brand=None,
        variant=None,
        volume_ml=750,
        package_quantity=1,
        score=0.95,
        offers=offers,
        winner=offers[0],
        runner_up=offers[1],
        saving_clp=1_000,
        saving_pct=1_000 / 22_000,
    )
    _, markup = format_search_results("producto", [result])
    assert markup is not None
    keyboard = markup["inline_keyboard"]
    assert len(keyboard) == 2
    assert [button["url"] for row in keyboard for button in row] == [
        "https://example.com/1",
        "https://example.com/2",
        "https://example.com/3",
        "https://example.com/4",
    ]


class _FakeAPI:
    def __init__(self):
        self.messages = []

    def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {}

    def close(self):
        return None


class _FakeApplication:
    def __init__(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.engine = engine
        self.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        self.max_age_hours = 72
        self.result_limit = 8
        now = datetime.now(timezone.utc)
        with self.SessionLocal() as session:
            store = Store(
                name="Licor3B",
                slug="licor3b",
                base_url="https://licor3b.cl/",
                connector_key="licor3b",
            )
            master = MasterProduct(
                canonical_name="Johnnie Walker Black 750 ml",
                normalized_key="johnnie walker black|750",
                search_text="johnnie walker black label 750 ml",
                aliases=[],
                package_quantity=1,
                volume_ml=750,
                status="active",
            )
            session.add_all([store, master])
            session.flush()
            session.add(
                Product(
                    store="Licor3B",
                    store_id=store.id,
                    master_product_id=master.id,
                    name="Johnnie Walker Black 750 ml",
                    url="https://licor3b.cl/black",
                    current_price=24990,
                    last_seen_at=now,
                )
            )
            session.commit()

    def search(self, query, *, limit=None):
        from app.search.engine import search_products

        with self.SessionLocal() as session:
            return search_products(session, query, limit=limit or 5)


def test_worker_answers_plain_text_search():
    app = _FakeApplication()
    api = _FakeAPI()
    settings = TelegramBotSettings(
        enabled=True,
        token="token",
        allowed_chat_ids=frozenset({123}),
        result_limit=5,
        max_age_hours=72,
        poll_timeout_seconds=25,
        retry_seconds=5,
    )
    bot = TelegramSearchBot(app, settings=settings, api=api)
    bot.handle_update(
        {
            "update_id": 10,
            "message": {
                "message_id": 5,
                "chat": {"id": 123},
                "from": {"id": 123, "is_bot": False},
                "text": "johnnie black 750",
            },
        }
    )
    assert len(api.messages) == 1
    assert "Johnnie Walker Black" in api.messages[0]["text"]
    assert api.messages[0]["reply_markup"]
    app.engine.dispose()


def test_worker_rejects_unauthorized_chat_once():
    app = _FakeApplication()
    api = _FakeAPI()
    settings = TelegramBotSettings(
        enabled=True,
        token="token",
        allowed_chat_ids=frozenset({123}),
        result_limit=5,
        max_age_hours=72,
        poll_timeout_seconds=25,
        retry_seconds=5,
    )
    bot = TelegramSearchBot(app, settings=settings, api=api)
    update = {
        "update_id": 11,
        "message": {
            "message_id": 6,
            "chat": {"id": 999},
            "from": {"id": 999, "is_bot": False},
            "text": "black",
        },
    }
    bot.handle_update(update)
    bot.handle_update(update)
    assert len(api.messages) == 1
    assert "privado" in api.messages[0]["text"]
    app.engine.dispose()
