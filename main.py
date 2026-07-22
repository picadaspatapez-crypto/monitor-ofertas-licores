import os
import sys
import requests


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno obligatoria: {name}")
    return value


def send_telegram_message(message: str) -> None:
    token = require_env("TELEGRAM_BOT_TOKEN")
    chat_id = require_env("TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message,
        },
        timeout=20,
    )
    response.raise_for_status()


def main() -> int:
    try:
        send_telegram_message(
            "✅ Monitor de ofertas conectado correctamente a Railway."
        )
        print("Mensaje enviado correctamente a Telegram.")
        return 0
    except Exception as exc:
        print(f"Error al ejecutar la prueba: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
