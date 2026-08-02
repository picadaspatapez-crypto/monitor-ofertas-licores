from __future__ import annotations

from typing import Any

import requests


class TelegramAPIError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token: str, *, request_timeout: int = 20) -> None:
        if not token:
            raise ValueError("Telegram token vacío.")
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.request_timeout = request_timeout
        self.session = requests.Session()

    def close(self) -> None:
        self.session.close()

    def _call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> Any:
        response = self.session.post(
            f"{self.base_url}/{method}",
            json=payload or {},
            timeout=timeout or self.request_timeout,
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise TelegramAPIError(
                f"Telegram devolvió una respuesta inválida ({response.status_code})."
            ) from exc
        if not response.ok or not data.get("ok"):
            description = data.get("description") or response.text[:300]
            raise TelegramAPIError(
                f"Telegram {method} falló ({response.status_code}): {description}"
            )
        return data.get("result")

    def get_me(self) -> dict[str, Any]:
        return dict(self._call("getMe") or {})

    def delete_webhook(self) -> bool:
        return bool(
            self._call(
                "deleteWebhook",
                {"drop_pending_updates": False},
            )
        )

    def set_commands(self) -> bool:
        commands = [
            {"command": "buscar", "description": "Buscar y comparar un producto"},
            {"command": "favorito", "description": "Seguir un producto"},
            {"command": "avisar", "description": "Crear una alerta de precio objetivo"},
            {"command": "misfavoritos", "description": "Ver tus productos seguidos"},
            {"command": "eliminarfavorito", "description": "Eliminar un favorito por ID"},
            {"command": "historial", "description": "Ver historial de un producto"},
            {"command": "oportunidades", "description": "Ver Opportunity Score alto"},
            {"command": "mejores", "description": "Ver mayores diferencias de precio"},
            {"command": "mas", "description": "Mostrar la siguiente página"},
            {"command": "estado", "description": "Ver estado del catálogo"},
            {"command": "ayuda", "description": "Mostrar ayuda y ejemplos"},
        ]
        return bool(self._call("setMyCommands", {"commands": commands}))

    def get_updates(
        self,
        *,
        offset: int | None,
        timeout_seconds: int,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout_seconds,
            "limit": limit,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._call(
            "getUpdates",
            payload,
            timeout=timeout_seconds + 15,
        )
        return [dict(item) for item in (result or [])]

    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to_message_id is not None:
            payload["reply_parameters"] = {
                "message_id": reply_to_message_id,
                "allow_sending_without_reply": True,
            }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return dict(self._call("sendMessage", payload) or {})
