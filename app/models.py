from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    base_url: Mapped[str] = mapped_column(String(1000))
    connector_key: Mapped[str] = mapped_column(String(120), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    requires_browser: Mapped[bool] = mapped_column(Boolean, default=False)
    country_code: Mapped[str] = mapped_column(String(2), default="CL")
    currency_code: Mapped[str] = mapped_column(String(3), default="CLP")
    comparison_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    diagnostic_mode: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    products: Mapped[list[Product]] = relationship(back_populates="store_record")
    scrape_runs: Mapped[list[ScrapeRun]] = relationship(back_populates="store")
    alerts: Mapped[list[Alert]] = relationship(back_populates="store")


class MasterProduct(Base):
    __tablename__ = "master_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(500))
    normalized_key: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    subcategory: Mapped[str | None] = mapped_column(String(120), nullable=True)
    volume_ml: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ean: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    variant: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    package_quantity: Mapped[int] = mapped_column(Integer, default=1)
    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    store_products: Mapped[list[Product]] = relationship(back_populates="master_product")
    matches: Mapped[list[ProductMatch]] = relationship(
        back_populates="master_product",
        cascade="all, delete-orphan",
    )


class Product(Base):
    """Publicación concreta de una tienda; equivale a store_products en el diseño."""

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("store", "url", name="uq_product_store_url"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store: Mapped[str] = mapped_column(String(80), index=True)
    store_id: Mapped[int | None] = mapped_column(
        ForeignKey("stores.id"), nullable=True, index=True
    )
    master_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("master_products.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1000))
    current_price: Mapped[int] = mapped_column(Integer)
    regular_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_pct: Mapped[float] = mapped_column(Float, default=0.0)
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    ean: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    missing_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unavailable_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_confirmed_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id"), nullable=True, index=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    store_record: Mapped[Store | None] = relationship(back_populates="products")
    master_product: Mapped[MasterProduct | None] = relationship(
        back_populates="store_products"
    )
    observations: Mapped[list[PriceObservation]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    alerts: Mapped[list[Alert]] = relationship(back_populates="product")
    matches: Mapped[list[ProductMatch]] = relationship(
        back_populates="store_product",
        cascade="all, delete-orphan",
    )


class ProductMatch(Base):
    __tablename__ = "product_matches"
    __table_args__ = (
        UniqueConstraint("store_product_id", name="uq_product_matches_store_product"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), index=True
    )
    master_product_id: Mapped[int] = mapped_column(
        ForeignKey("master_products.id"), index=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    matching_method: Mapped[str] = mapped_column(String(50), default="exact_normalized")
    review_status: Mapped[str] = mapped_column(String(30), default="automatic", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    store_product: Mapped[Product] = relationship(back_populates="matches")
    master_product: Mapped[MasterProduct] = relationship(back_populates="matches")


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    products_found: Mapped[int] = mapped_column(Integer, default=0)
    products_created: Mapped[int] = mapped_column(Integer, default=0)
    products_updated: Mapped[int] = mapped_column(Integer, default=0)
    products_failed: Mapped[int] = mapped_column(Integer, default=0)
    price_changes: Mapped[int] = mapped_column(Integer, default=0)
    sections_discovered: Mapped[int] = mapped_column(Integer, default=0)
    sections_visited: Mapped[int] = mapped_column(Integer, default=0)
    sections_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    sections_failed: Mapped[int] = mapped_column(Integer, default=0)
    pages_visited: Mapped[int] = mapped_column(Integer, default=0)
    cards_seen: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_removed: Mapped[int] = mapped_column(Integer, default=0)
    structural_warnings: Mapped[int] = mapped_column(Integer, default=0)
    health_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    health_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    store: Mapped[Store] = relationship(back_populates="scrape_runs")
    observations: Mapped[list[PriceObservation]] = relationship(
        back_populates="scrape_run"
    )
    alerts: Mapped[list[Alert]] = relationship(back_populates="scrape_run")


class PriceObservation(Base):
    """Historial inmutable de precios; equivale a price_history en el diseño."""

    __tablename__ = "price_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    scrape_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id"), nullable=True, index=True
    )
    price: Mapped[int] = mapped_column(Integer)
    regular_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_pct: Mapped[float] = mapped_column(Float, default=0.0)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    product: Mapped[Product] = relationship(back_populates="observations")
    scrape_run: Mapped[ScrapeRun | None] = relationship(back_populates="observations")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id"), nullable=True, index=True
    )
    store_id: Mapped[int | None] = mapped_column(
        ForeignKey("stores.id"), nullable=True, index=True
    )
    scrape_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id"), nullable=True, index=True
    )
    alert_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    channel: Mapped[str] = mapped_column(String(30), default="telegram")
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    deduplication_key: Mapped[str] = mapped_column(String(255), unique=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product | None] = relationship(back_populates="alerts")
    store: Mapped[Store | None] = relationship(back_populates="alerts")
    scrape_run: Mapped[ScrapeRun | None] = relationship(back_populates="alerts")


class ProductPriceQuote(Base):
    """Precio vigente de una publicación para un contexto/audiencia concreta."""

    __tablename__ = "product_price_quotes"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "price_type", "audience_key",
            name="uq_product_price_quote_context",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    price: Mapped[int] = mapped_column(Integer)
    regular_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_type: Mapped[str] = mapped_column(String(30), default="PUBLIC", index=True)
    audience_key: Mapped[str] = mapped_column(String(80), default="public", index=True)
    eligibility_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PriceQuoteObservation(Base):
    """Historial inmutable de precios contextuales (público, socio, tarjeta, cupón)."""

    __tablename__ = "price_quote_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    scrape_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id"), nullable=True, index=True
    )
    price: Mapped[int] = mapped_column(Integer)
    regular_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_type: Mapped[str] = mapped_column(String(30), default="PUBLIC", index=True)
    audience_key: Mapped[str] = mapped_column(String(80), default="public", index=True)
    eligibility_required: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PersonalOpportunitySnapshot(Base):
    """Opportunity Score usando precios habilitados para el perfil personal."""

    __tablename__ = "personal_opportunity_snapshots"

    master_product_id: Mapped[int] = mapped_column(
        ForeignKey("master_products.id"), primary_key=True
    )
    score: Mapped[float] = mapped_column(Float, index=True)
    classification: Mapped[str] = mapped_column(String(30), index=True)
    winner_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    winner_store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True, index=True)
    winner_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winner_price_type: Mapped[str] = mapped_column(String(30), default="PUBLIC")
    winner_audience_key: Mapped[str] = mapped_column(String(80), default="public")
    saving_clp: Mapped[int] = mapped_column(Integer, default=0)
    saving_pct: Mapped[float] = mapped_column(Float, default=0.0)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class MatchingRule(Base):
    """Regla manual persistente para forzar o impedir equivalencias."""

    __tablename__ = "matching_rules"
    __table_args__ = (
        UniqueConstraint(
            "rule_type", "left_key", "right_key",
            name="uq_matching_rule_pair",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_type: Mapped[str] = mapped_column(String(30), index=True)
    left_key: Mapped[str] = mapped_column(String(500), index=True)
    right_key: Mapped[str] = mapped_column(String(500), index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MasterPriceStatistic(Base):
    __tablename__ = "master_price_statistics"

    master_product_id: Mapped[int] = mapped_column(
        ForeignKey("master_products.id"), primary_key=True
    )
    current_best_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_30d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_90d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_90d: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_90d: Mapped[float | None] = mapped_column(Float, nullable=True)
    historical_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observations_30d: Mapped[int] = mapped_column(Integer, default=0)
    observations_90d: Mapped[int] = mapped_column(Integer, default=0)
    observations_total: Mapped[int] = mapped_column(Integer, default=0)
    discount_frequency_90d: Mapped[float] = mapped_column(Float, default=0.0)
    days_at_current_price: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OpportunitySnapshot(Base):
    __tablename__ = "opportunity_snapshots"

    master_product_id: Mapped[int] = mapped_column(
        ForeignKey("master_products.id"), primary_key=True
    )
    score: Mapped[float] = mapped_column(Float, index=True)
    classification: Mapped[str] = mapped_column(String(30), index=True)
    winner_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id"), nullable=True, index=True
    )
    winner_store_id: Mapped[int | None] = mapped_column(
        ForeignKey("stores.id"), nullable=True, index=True
    )
    winner_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saving_clp: Mapped[int] = mapped_column(Integer, default=0)
    saving_pct: Mapped[float] = mapped_column(Float, default=0.0)
    match_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    history_position: Mapped[float] = mapped_column(Float, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float, default=0.0)
    scarcity_score: Mapped[float] = mapped_column(Float, default=0.0)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class TelegramBotState(Base):
    """Small persistent key/value store for Telegram polling offsets."""

    __tablename__ = "telegram_bot_state"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TelegramFavorite(Base):
    """Producto seguido por un chat autorizado de Telegram."""

    __tablename__ = "telegram_favorites"
    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "master_product_id",
            name="uq_telegram_favorite_chat_master",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    master_product_id: Mapped[int] = mapped_column(
        ForeignKey("master_products.id"), index=True
    )
    target_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notify_on_price_drop: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_new_store: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_winner_change: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_back_in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Estado de la última evaluación. Se usa para detectar cambios sin repetir avisos.
    last_best_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_winner_store: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_store_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    was_available: Mapped[bool] = mapped_column(Boolean, default=False)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class FavoriteAlert(Base):
    """Cola persistente de alertas personalizadas de favoritos."""

    __tablename__ = "favorite_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    favorite_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_favorites.id"), index=True
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    event_types: Mapped[list] = mapped_column(JSON, default=list)
    run_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    deduplication_key: Mapped[str] = mapped_column(String(255), unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    current_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winner_store: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
