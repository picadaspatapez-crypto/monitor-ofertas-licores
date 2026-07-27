from __future__ import annotations

import os
import threading

from app.search.web import SearchApplication, SearchServer
from app.telegram_bot import TelegramSearchBot
from app.version import APP_VERSION, RELEASE_NAME


def main() -> int:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    application = SearchApplication()
    server = SearchServer((host, port), application)
    stop_event = threading.Event()
    bot = TelegramSearchBot(application)
    bot_thread = threading.Thread(
        target=bot.run_forever,
        args=(stop_event,),
        name="telegram-search-bot",
        daemon=True,
    )
    bot_thread.start()

    print(
        f"Servicio interactivo v{APP_VERSION} · {RELEASE_NAME} · "
        f"web=http://{host}:{port} · bot={'activo' if bot.enabled else 'pendiente'}.",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.shutdown()
        server.server_close()
        bot_thread.join(timeout=5)
        application.engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
