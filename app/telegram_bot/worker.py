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
from app.models import MasterProduct, Product, TelegramFavorite
from app.search.web import SearchApplication
from app.telegram_bot.api import TelegramAPI, TelegramAPIError
from app.telegram_bot.commands import BotCommand, parse_command
from app.telegram_bot.config import TelegramBotSettings
from app.telegram_bot.formatting import (
    favorite_delete_help_message,
    favorite_help_message,
    favorite_target_help_message,
    format_favorite_deleted,
    format_favorite_resolution_error,
    format_favorite_saved,
    format_favorites_list,
    format_search_results,
    help_message,
    search_help_message,
    status_message,
    unauthorized_message,
)
from app.telegram_bot.state import load_next_update_id, save_next_update_id


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

    def _catalog_status(self, chat_id: int) -> tuple[int, int, datetime | None, int]:
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
                    select(func.count(Product.id)).where(
                        Product.current_price > 0,
                        Product.last_seen_at >= cutoff,
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
        if latest_seen_at is not None and latest_seen_at.tzinfo is None:
            latest_seen_at = latest_seen_at.replace(tzinfo=timezone.utc)
        return active_masters, fresh_products, latest_seen_at, favorite_count

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
        if command.name == "status":
            active, fresh, latest, favorites = self._catalog_status(chat_id)
            self._send(
                chat_id=chat_id,
                message_id=message_id,
                text=status_message(
                    active_masters=active,
                    fresh_products=fresh,
                    latest_seen_at=latest,
                    max_age_hours=self.settings.max_age_hours,
                    favorites=favorites,
                ),
            )
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
        if command.name == "search":
            try:
                results = self.application.search(
                    command.query,
                    limit=self.settings.result_limit,
                )
                text, markup = format_search_results(command.query, results)
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
