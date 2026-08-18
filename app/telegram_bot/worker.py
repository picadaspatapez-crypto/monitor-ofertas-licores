from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.favorites import (
    add_or_update_favorite,
    deactivate_favorite,
    list_favorites,
    resolve_favorite_query,
)
from app.intelligence.queries import commercial_radar, historical_floor_opportunities, top_opportunities
from app.intelligence.personal import top_personal_opportunities
from app.models import MasterProduct, Product, ScrapeRun, Store, TelegramFavorite
from app.search.web import SearchApplication
from app.telegram_bot.api import TelegramAPI, TelegramAPIError
from app.telegram_bot.commands import BotCommand, parse_command
from app.telegram_bot.config import TelegramBotSettings
from app.telegram_bot.formatting import (
    favorite_delete_help_message,
    format_history_result,
    format_opportunities,
    history_help_message,
    personal_history_help_message,
    format_personal_history_result,
    favorite_help_message,
    favorite_target_help_message,
    format_favorite_deleted,
    format_favorite_resolution_error,
    format_favorite_saved,
    format_favorites_list,
    format_search_results,
    help_message,
    no_results_message,
    quality_message,
    search_help_message,
    status_message,
    StoreStatusView,
    unauthorized_message,
)
from app.telegram_bot.state import (
    load_next_update_id,
    load_search_page,
    save_next_update_id,
    save_search_page,
)


class TelegramSearchBot:
    def __init__(
        self,
        application: SearchApplication,
        *,
        settings: TelegramBotSettings | None = None,
        api: TelegramAPI | None = None,
    ) -> None:
        self.application = application
        self.settings = settings or TelegramBotSettings.from_env()
        self.api = api or (
            TelegramAPI(self.settings.token) if self.settings.enabled else None
        )
        self.username: str | None = None
        self._unauthorized_notified: set[int] = set()

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.enabled
            and self.api is not None
            and self.settings.allowed_chat_ids
        )

    def _authorized(self, chat_id: int) -> bool:
        return chat_id in self.settings.allowed_chat_ids

    def _search_catalog(self, query: str, *, limit: int, offset: int = 0, price_mode: str = "public"):
        try:
            return self.application.search(query, limit=limit, offset=offset, price_mode=price_mode)
        except TypeError as exc:
            # Compatibilidad con implementaciones antiguas y dobles de prueba.
            message = str(exc)
            if price_mode != "public" and "price_mode" in message:
                return self.application.search(query, limit=limit, offset=offset)
            if "offset" not in message or offset:
                raise
            return self.application.search(query, limit=limit)

    def _send(
        self,
        *,
        chat_id: int,
        text: str,
        message_id: int | None,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        assert self.api is not None
        self.api.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=message_id,
            reply_markup=reply_markup,
        )

    def _catalog_status(
        self, chat_id: int
    ) -> tuple[int, int, datetime | None, int, tuple[StoreStatusView, ...]]:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=self.settings.max_age_hours
        )
        with self.application.SessionLocal() as session:
            active_masters = int(
                session.scalar(
                    select(func.count(MasterProduct.id)).where(
                        MasterProduct.status == "active"
                    )
                )
                or 0
            )
            fresh_products = int(
                session.scalar(
                    select(func.count(Product.id))
                    .join(Store, Store.id == Product.store_id)
                    .where(
                        Product.current_price > 0,
                        Product.last_seen_at >= cutoff,
                        Product.is_available.is_(True),
                        Store.is_active.is_(True),
                    )
                )
                or 0
            )
            latest_seen_at = session.scalar(select(func.max(Product.last_seen_at)))
            favorite_count = int(
                session.scalar(
                    select(func.count(TelegramFavorite.id)).where(
                        TelegramFavorite.chat_id == chat_id,
                        TelegramFavorite.is_active.is_(True),
                    )
                )
                or 0
            )
            store_views: list[StoreStatusView] = []
            stores = list(session.scalars(select(Store).where(Store.is_active.is_(True)).order_by(Store.name)))
            for store in stores:
                run = session.scalar(
                    select(ScrapeRun)
                    .where(ScrapeRun.store_id == store.id)
                    .order_by(ScrapeRun.started_at.desc(), ScrapeRun.id.desc())
                    .limit(1)
                )
                finished_at = run.finished_at if run is not None else None
                if finished_at is not None and finished_at.tzinfo is None:
                    finished_at = finished_at.replace(tzinfo=timezone.utc)
                real_run = session.scalar(
                    select(ScrapeRun)
                    .where(
                        ScrapeRun.store_id == store.id,
                        ScrapeRun.status == "success",
                        ScrapeRun.health_status == "HEALTHY",
                        ScrapeRun.finished_at.is_not(None),
                    )
                    .order_by(ScrapeRun.finished_at.desc(), ScrapeRun.id.desc())
                    .limit(1)
                )
                last_real_at = real_run.finished_at if real_run is not None else None
                if last_real_at is not None and last_real_at.tzinfo is None:
                    last_real_at = last_real_at.replace(tzinfo=timezone.utc)
                interval_hours = 12 if store.connector_key == "elmundodelvino" else 6
                next_due_at = (
                    finished_at + timedelta(hours=interval_hours)
                    if finished_at is not None
                    else None
                )
                source = None
                source_run = real_run or run
                if source_run is not None and isinstance(source_run.metrics_json, dict):
                    source = source_run.metrics_json.get("discovery_source")
                store_views.append(
                    StoreStatusView(
                        name=store.name,
                        run_status=run.status if run is not None else "never",
                        health_status=run.health_status if run is not None else None,
                        products_found=int((real_run or run).products_found or 0) if (real_run or run) is not None else 0,
                        finished_at=finished_at,
                        last_real_at=last_real_at,
                        next_due_at=next_due_at,
                        source=str(source) if source else None,
                    )
                )
        if latest_seen_at is not None and latest_seen_at.tzinfo is None:
            latest_seen_at = latest_seen_at.replace(tzinfo=timezone.utc)
        return active_masters, fresh_products, latest_seen_at, favorite_count, tuple(store_views)

    def _handle_command(
        self,
        command: BotCommand,
        *,
        chat_id: int,
        message_id: int | None,
    ) -> None:
        if command.name == "help":
            self._send(
                chat_id=chat_id,
                message_id=message_id,
                text=help_message(self.username),
            )
            return
        if command.name == "search_help":
            self._send(
                chat_id=chat_id,
                message_id=message_id,
                text=search_help_message(),
            )
            return
        if command.name == "history_help":
            self._send(
                chat_id=chat_id,
                message_id=message_id,
                text=history_help_message(),
            )
            return
        if command.name == "personal_history_help":
            self._send(
                chat_id=chat_id,
                message_id=message_id,
                text=personal_history_help_message(),
            )
            return
        if command.name == "status":
            active, fresh, latest, favorites, stores = self._catalog_status(chat_id)
            self._send(
                chat_id=chat_id,
                message_id=message_id,
                text=status_message(
                    active_masters=active,
                    fresh_products=fresh,
                    latest_seen_at=latest,
                    max_age_hours=self.settings.max_age_hours,
                    favorites=favorites,
                    stores=stores,
                ),
            )
            return
        if command.name == "quality":
            try:
                rows, blocked, warnings = self.application.quality_incidents(limit=100)
                text = quality_message(rows, blocked=blocked, warnings=warnings, limit=10)
            except Exception as exc:
                print(f"BOT quality error ({type(exc).__name__}: {exc}).", flush=True)
                text = "⚠️ No pude consultar la calidad de datos en este momento."
            self._send(chat_id=chat_id, message_id=message_id, text=text)
            return
        if command.name == "history":
            try:
                results = self._search_catalog(command.query, limit=1)
                text = format_history_result(command.query, results[0] if results else None)
            except Exception as exc:
                print(f"BOT history error ({type(exc).__name__}: {exc}).", flush=True)
                text = "⚠️ No pude consultar el historial en este momento."
            self._send(chat_id=chat_id, message_id=message_id, text=text)
            return
        if command.name in {"commercial_radar", "historical_floors"}:
            try:
                with self.application.SessionLocal() as session:
                    views = (
                        commercial_radar(session, limit=15, minimum_score=70.0)
                        if command.name == "commercial_radar"
                        else historical_floor_opportunities(session, limit=15)
                    )
                if command.name == "commercial_radar":
                    strict_signal = any(
                        getattr(view, "price_event", "NORMAL") != "NORMAL"
                        and float(getattr(view, "score", 0.0) or 0.0) >= 70.0
                        for view in views
                    )
                    title = (
                        "Radar comercial · señales verificadas"
                        if strict_signal
                        else "Radar comercial · mejores oportunidades actuales"
                    )
                else:
                    strict_floor = any(
                        getattr(view, "price_event", "NORMAL")
                        in {"NEW_HISTORICAL_MIN", "AT_HISTORICAL_MIN", "NEAR_HISTORICAL_MIN"}
                        for view in views
                    )
                    title = (
                        "Precios en o cerca del mínimo histórico"
                        if strict_floor
                        else "Precios más cercanos a su mínimo histórico"
                    )
                text, markup = format_opportunities(views, title=title)
            except Exception as exc:
                print(f"BOT commercial radar error ({type(exc).__name__}: {exc}).", flush=True)
                text, markup = "⚠️ No pude consultar la inteligencia comercial.", None
            self._send(
                chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup
            )
            return

        if command.name in {"opportunities", "best_prices"}:
            try:
                with self.application.SessionLocal() as session:
                    views = top_opportunities(
                        session,
                        limit=20,
                        minimum_score=70.0 if command.name == "opportunities" else 0.0,
                        order="score" if command.name == "opportunities" else "saving",
                    )
                text, markup = format_opportunities(
                    views,
                    title=(
                        "Oportunidades verificadas"
                        if command.name == "opportunities"
                        else "Mejores diferencias entre tiendas"
                    ),
                )
            except Exception as exc:
                print(f"BOT opportunities error ({type(exc).__name__}: {exc}).", flush=True)
                text, markup = "⚠️ No pude consultar las oportunidades.", None
            self._send(
                chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup
            )
            return
        if command.name == "personal_search":
            try:
                results = self._search_catalog(command.query, limit=self.settings.page_size, price_mode="personal")
                text, markup = format_search_results(
                    command.query, results, page=0, page_size=self.settings.page_size, has_more=False
                ) if results else (no_results_message(command.query), None)
                text = "🟣 <b>Comparador personal</b>\nIncluye tu precio socio CAV cuando corresponde.\n\n" + text
            except Exception as exc:
                print(f"BOT personal search error ({type(exc).__name__}: {exc}).", flush=True)
                text, markup = "⚠️ No pude consultar el comparador personal.", None
            self._send(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
            return
        if command.name == "personal_history":
            try:
                results = self._search_catalog(command.query, limit=1, price_mode="personal")
                text = format_personal_history_result(command.query, results[0] if results else None)
            except Exception as exc:
                print(f"BOT personal history error ({type(exc).__name__}: {exc}).", flush=True)
                text = "⚠️ No pude consultar el historial personal en este momento."
            self._send(chat_id=chat_id, message_id=message_id, text=text)
            return
        if command.name == "personal_opportunities":
            try:
                with self.application.SessionLocal() as session:
                    views = top_personal_opportunities(session, limit=20)
                if not views:
                    text = "🟣 Comparador personal: todavía no hay suficientes coincidencias contextuales."
                else:
                    lines = ["🟣 Oportunidades personales", "", "Incluye tu precio socio CAV sin modificar el comparador público.", ""]
                    for index, view in enumerate(views, start=1):
                        context = "socio" if view.price_type == "MEMBER" else view.price_type.casefold()
                        lines.extend([
                            f"{index}. {view.canonical_name}",
                            f"   {view.winner_store}: ${view.winner_price:,} ({context})".replace(",", "."),
                            f"   Ahorro vs 2ª opción: ${view.saving_clp:,} · {view.saving_pct:.1%} · score {view.score:.0f}".replace(",", "."),
                        ])
                        if view.personal_advantage_clp > 0:
                            lines.append(
                                f"   Ventaja vs mercado público: ${view.personal_advantage_clp:,} · {view.personal_advantage_pct:.1%}".replace(",", ".")
                            )
                        lines.extend([view.url, ""])
                    text = "\n".join(lines).strip()
            except Exception as exc:
                print(f"BOT personal opportunities error ({type(exc).__name__}: {exc}).", flush=True)
                text = "⚠️ No pude consultar la vista personal en este momento."
            self._send(chat_id=chat_id, message_id=message_id, text=text)
            return
        if command.name == "favorite_help":
            self._send(
                chat_id=chat_id,
                message_id=message_id,
                text=favorite_help_message(),
            )
            return
        if command.name == "favorite_target_help":
            self._send(
                chat_id=chat_id,
                message_id=message_id,
                text=favorite_target_help_message(),
            )
            return
        if command.name == "favorite_delete_help":
            self._send(
                chat_id=chat_id,
                message_id=message_id,
                text=favorite_delete_help_message(),
            )
            return
        if command.name in {"favorite_add", "favorite_target"}:
            try:
                with self.application.SessionLocal() as session:
                    resolution = resolve_favorite_query(
                        session,
                        command.query,
                        max_age_hours=self.settings.max_age_hours,
                    )
                    if resolution.result is None:
                        text = format_favorite_resolution_error(command.query, resolution)
                    else:
                        favorite, created = add_or_update_favorite(
                            session,
                            chat_id=chat_id,
                            result=resolution.result,
                            target_price=(
                                command.value if command.name == "favorite_target" else None
                            ),
                        )
                        session.commit()
                        text = format_favorite_saved(
                            result=resolution.result,
                            favorite_id=int(favorite.id),
                            created=created,
                            target_price=favorite.target_price,
                        )
            except Exception as exc:
                print(f"BOT favorite error ({type(exc).__name__}: {exc}).", flush=True)
                text = "⚠️ No pude guardar el favorito en este momento."
            self._send(chat_id=chat_id, message_id=message_id, text=text)
            return
        if command.name == "favorite_list":
            try:
                with self.application.SessionLocal() as session:
                    views = list_favorites(
                        session,
                        chat_id=chat_id,
                        max_age_hours=self.settings.max_age_hours,
                    )
                text = format_favorites_list(views)
            except Exception as exc:
                print(f"BOT favorite list error ({type(exc).__name__}: {exc}).", flush=True)
                text = "⚠️ No pude consultar tus favoritos en este momento."
            self._send(chat_id=chat_id, message_id=message_id, text=text)
            return
        if command.name == "favorite_delete":
            try:
                with self.application.SessionLocal() as session:
                    deleted = deactivate_favorite(
                        session,
                        chat_id=chat_id,
                        favorite_id=int(command.value or 0),
                    )
                    session.commit()
                text = format_favorite_deleted(int(command.value or 0), deleted)
            except Exception as exc:
                print(f"BOT favorite delete error ({type(exc).__name__}: {exc}).", flush=True)
                text = "⚠️ No pude eliminar el favorito en este momento."
            self._send(chat_id=chat_id, message_id=message_id, text=text)
            return
        if command.name in {"search", "search_more"}:
            try:
                if command.name == "search":
                    query, offset = command.query, 0
                else:
                    with self.application.SessionLocal() as session:
                        saved_page = load_search_page(session, chat_id=chat_id)
                    if saved_page is None:
                        self._send(
                            chat_id=chat_id,
                            message_id=message_id,
                            text="No hay una búsqueda anterior. Usa /buscar seguido del producto.",
                        )
                        return
                    query, offset = saved_page
                requested = self.settings.result_limit
                page = self._search_catalog(
                    query,
                    limit=requested + 1,
                    offset=offset,
                )
                has_more = len(page) > requested
                results = page[:requested]
                next_offset = offset + len(results)
                with self.application.SessionLocal() as session:
                    save_search_page(
                        session, chat_id=chat_id, query=query, offset=next_offset
                    )
                    session.commit()
                text, markup = format_search_results(
                    query,
                    results,
                    start_index=offset + 1,
                    has_more=has_more,
                )
            except Exception as exc:
                print(
                    f"BOT search error ({type(exc).__name__}: {exc}).",
                    flush=True,
                )
                text = (
                    "⚠️ No pude consultar el catálogo en este momento. "
                    "Intenta nuevamente en unos segundos."
                )
                markup = None
            self._send(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=markup,
            )
            return
        if command.name == "unknown":
            self._send(
                chat_id=chat_id,
                message_id=message_id,
                text="Comando no reconocido. Usa /ayuda para ver las opciones.",
            )

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        sender = message.get("from") or {}
        if isinstance(sender, dict) and sender.get("is_bot"):
            return
        chat = message.get("chat") or {}
        try:
            chat_id = int(chat.get("id"))
        except (TypeError, ValueError):
            return
        message_id_raw = message.get("message_id")
        message_id = int(message_id_raw) if isinstance(message_id_raw, int) else None

        if not self._authorized(chat_id):
            if chat_id not in self._unauthorized_notified:
                self._unauthorized_notified.add(chat_id)
                self._send(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=unauthorized_message(),
                )
            print(f"BOT chat no autorizado ignorado: {chat_id}", flush=True)
            return

        text = message.get("text")
        command = parse_command(text if isinstance(text, str) else None)
        if command.name == "ignore":
            return
        self._handle_command(
            command,
            chat_id=chat_id,
            message_id=message_id,
        )

    def _load_offset(self) -> int | None:
        with self.application.SessionLocal() as session:
            return load_next_update_id(session)

    def _save_offset(self, value: int) -> None:
        with self.application.SessionLocal() as session:
            save_next_update_id(session, value)
            session.commit()

    def prepare(self) -> None:
        if not self.enabled:
            return
        assert self.api is not None
        self.api.delete_webhook()
        self.api.set_commands()
        me = self.api.get_me()
        self.username = str(me.get("username") or "").strip() or None
        identity = f"@{self.username}" if self.username else str(me.get("id", "bot"))
        print(
            f"BOT Telegram listo: {identity}; chats autorizados="
            f"{sorted(self.settings.allowed_chat_ids)}.",
            flush=True,
        )

    def run_forever(self, stop_event: threading.Event) -> None:
        if not self.enabled:
            reason = "sin TELEGRAM_BOT_TOKEN"
            if self.settings.enabled and not self.settings.allowed_chat_ids:
                reason = "sin TELEGRAM_CHAT_ID/TELEGRAM_ALLOWED_CHAT_IDS"
            print(f"BOT Telegram deshabilitado: {reason}.", flush=True)
            return

        assert self.api is not None
        prepared = False
        offset = self._load_offset()
        while not stop_event.is_set():
            if not prepared:
                try:
                    self.prepare()
                    prepared = True
                except Exception as exc:
                    print(
                        f"BOT no pudo inicializarse ({type(exc).__name__}: {exc}); reintentará.",
                        flush=True,
                    )
                    stop_event.wait(self.settings.retry_seconds)
                    continue
            try:
                updates = self.api.get_updates(
                    offset=offset,
                    timeout_seconds=self.settings.poll_timeout_seconds,
                )
                for update in updates:
                    update_id_raw = update.get("update_id")
                    if not isinstance(update_id_raw, int):
                        continue
                    try:
                        self.handle_update(update)
                    except Exception as exc:
                        print(
                            f"BOT error procesando update {update_id_raw}: "
                            f"{type(exc).__name__}: {exc}",
                            flush=True,
                        )
                    finally:
                        offset = update_id_raw + 1
                        self._save_offset(offset)
            except TelegramAPIError as exc:
                print(f"BOT Telegram API: {exc}", flush=True)
                stop_event.wait(self.settings.retry_seconds)
            except Exception as exc:
                print(
                    f"BOT polling error ({type(exc).__name__}: {exc}); reintentando.",
                    flush=True,
                )
                stop_event.wait(self.settings.retry_seconds)

        if self.api is not None:
            self.api.close()
