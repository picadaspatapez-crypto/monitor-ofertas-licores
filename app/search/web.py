from __future__ import annotations

import hmac
import html
import json
import os
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from sqlalchemy import text

from app.database import create_database
from app.search.engine import SearchResult, search_products
from app.search.formatting import format_clp, format_datetime_cl, result_to_dict
from app.version import APP_VERSION, RELEASE_NAME


_COOKIE_NAME = "liquor_search_access"
_STATIC_CSS = Path(__file__).with_name("static") / "search.css"


def _positive_int(name: str, default: int, *, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} debe ser un número entero.") from exc
    if value < 1:
        raise RuntimeError(f"{name} debe ser mayor que cero.")
    return min(value, maximum) if maximum is not None else value


def _page(title: str, body: str) -> bytes:
    document = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="/static/search.css">
</head>
<body><main class="shell">{body}</main></body>
</html>"""
    return document.encode("utf-8")


def _login_html(*, error: str | None = None, next_path: str = "/buscar") -> bytes:
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    body = f"""
<section class="panel compact">
  <div class="eyebrow">Monitor de Licores · v{APP_VERSION}</div>
  <h1>Acceso al buscador</h1>
  <p>Ingresa la clave privada configurada en Railway.</p>
  {error_html}
  <form method="post" action="/acceso" class="stack">
    <input type="hidden" name="next" value="{html.escape(next_path, quote=True)}">
    <label for="token">Clave de acceso</label>
    <input id="token" name="token" type="password" autocomplete="current-password" required autofocus>
    <button type="submit">Entrar</button>
  </form>
</section>"""
    return _page("Acceso al buscador", body)


def _setup_html() -> bytes:
    body = f"""
<section class="panel compact">
  <div class="eyebrow">Monitor de Licores · v{APP_VERSION}</div>
  <h1>Configuración pendiente</h1>
  <p>Agrega la variable <code>SEARCH_ACCESS_TOKEN</code> al servicio web de Railway y vuelve a desplegarlo.</p>
  <p class="muted">El scraper cron puede seguir funcionando con normalidad.</p>
</section>"""
    return _page("Configuración pendiente", body)


def _result_html(result: SearchResult) -> str:
    meta: list[str] = []
    if result.brand:
        meta.append(f"<span>{html.escape(result.brand)}</span>")
    if result.volume_ml:
        meta.append(f"<span>{result.volume_ml} ml</span>")
    if result.package_quantity > 1:
        meta.append(f"<span>Pack {result.package_quantity}</span>")

    saving = ""
    if result.runner_up and result.saving_clp > 0:
        saving = (
            '<div class="saving">Ahorro frente a la siguiente tienda: '
            f"<strong>{format_clp(result.saving_clp)}</strong> "
            f"({result.saving_pct * 100:.1f}%)</div>"
        )

    offers: list[str] = []
    for offer in result.offers:
        best = " best" if offer.product_id == result.winner.product_id else ""
        regular = (
            f"<del>{format_clp(offer.regular_price)}</del>"
            if offer.regular_price and offer.regular_price > offer.price
            else ""
        )
        offers.append(
            f"""<div class="offer{best}">
<div><strong>{html.escape(offer.store_name)}</strong>
<p>{html.escape(offer.product_name)}</p>
<small>Actualizado {html.escape(format_datetime_cl(offer.last_seen_at))}</small></div>
<div class="offer-price">{regular}<strong>{format_clp(offer.price)}</strong>
<a href="{html.escape(offer.url, quote=True)}" target="_blank" rel="noopener noreferrer">Ver producto</a></div>
</div>"""
        )

    return f"""<article class="result-card">
<div class="result-head"><div>
<div class="score">Coincidencia {result.score * 100:.0f}%</div>
<h2>{html.escape(result.canonical_name)}</h2>
<div class="meta">{''.join(meta)}</div></div>
<div class="winner"><span>Mejor precio</span><strong>{format_clp(result.winner.price)}</strong>
<small>{html.escape(result.winner.store_name)}</small></div></div>
{saving}<div class="offers">{''.join(offers)}</div></article>"""


def _search_html(
    *,
    query: str,
    results: list[SearchResult],
    max_age_hours: int,
    error: str | None = None,
) -> bytes:
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    empty = ""
    if query and not results and not error:
        empty = """<section class="empty"><h2>No encontré coincidencias</h2>
<p>Prueba con menos palabras o sin indicar el volumen.</p></section>"""
    body = f"""
<header class="hero"><div>
<div class="eyebrow">Catálogo unificado · v{APP_VERSION}</div>
<h1>Busca una botella y compara precios</h1>
<p>Prueba con “johnnie black 750”, “jack honey” o “mistral 35 1 litro”.</p>
</div><form method="post" action="/salir"><button class="ghost" type="submit">Salir</button></form></header>
<form class="searchbar" method="get" action="/buscar">
<input name="q" value="{html.escape(query, quote=True)}" placeholder="Nombre, marca, variante o volumen" maxlength="120" autofocus>
<button type="submit">Buscar</button></form>
{error_html}{empty}<section class="results">{''.join(_result_html(item) for item in results)}</section>
<footer>Solo se muestran precios observados durante las últimas {max_age_hours} horas.</footer>"""
    return _page("Buscar precios", body)


class SearchApplication:
    def __init__(self) -> None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("Falta la variable obligatoria: DATABASE_URL")
        self.access_token = os.getenv("SEARCH_ACCESS_TOKEN", "").strip()
        self.result_limit = _positive_int("SEARCH_RESULT_LIMIT", 8, maximum=20)
        self.max_age_hours = _positive_int("SEARCH_MAX_AGE_HOURS", 72, maximum=24 * 30)
        self.engine, self.SessionLocal = create_database(database_url)

    def token_matches(self, value: str | None) -> bool:
        return bool(
            self.access_token
            and value
            and hmac.compare_digest(value, self.access_token)
        )

    def authorized(self, handler: BaseHTTPRequestHandler) -> bool:
        cookie = SimpleCookie(handler.headers.get("Cookie", ""))
        cookie_token = cookie.get(_COOKIE_NAME)
        bearer = handler.headers.get("Authorization", "")
        header_token = bearer[7:].strip() if bearer.startswith("Bearer ") else None
        return self.token_matches(cookie_token.value if cookie_token else None) or self.token_matches(header_token)

    def search(self, query: str, *, limit: int | None = None) -> list[SearchResult]:
        with self.SessionLocal() as session:
            return search_products(
                session,
                query,
                limit=limit or self.result_limit,
                max_age_hours=self.max_age_hours,
            )


class SearchHandler(BaseHTTPRequestHandler):
    server_version = "LiquorSearch/4.7"

    @property
    def app(self) -> SearchApplication:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        print(f"WEB {self.address_string()} · {format % args}", flush=True)

    def _send(
        self,
        status: int,
        content: bytes,
        *,
        content_type: str = "text/html; charset=utf-8",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def _redirect(self, location: str, *, cookie: str | None = None) -> None:
        headers = {"Location": location}
        if cookie:
            headers["Set-Cookie"] = cookie
        self._send(HTTPStatus.SEE_OTHER, b"", headers=headers)

    def _require_auth(self, *, api: bool = False) -> bool:
        if not self.app.access_token:
            if api:
                self._send(503, b'{"error":"SEARCH_ACCESS_TOKEN missing"}', content_type="application/json")
            else:
                self._send(503, _setup_html())
            return False
        if self.app.authorized(self):
            return True
        if api:
            self._send(401, b'{"error":"unauthorized"}', content_type="application/json")
        else:
            self._redirect("/acceso?" + urlencode({"next": self.path}))
        return False

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query_args = parse_qs(parsed.query)

        if parsed.path == "/health":
            try:
                with self.app.SessionLocal() as session:
                    session.execute(text("SELECT 1"))
                payload = {
                    "status": "ok",
                    "version": APP_VERSION,
                    "release": RELEASE_NAME,
                    "service": "search-and-telegram",
                    "auth_configured": bool(self.app.access_token),
                    "telegram_token_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip()),
                }
                self._send(200, json.dumps(payload).encode(), content_type="application/json")
            except Exception as exc:
                payload = {"status": "error", "error": type(exc).__name__}
                self._send(503, json.dumps(payload).encode(), content_type="application/json")
            return

        if parsed.path == "/static/search.css":
            content = _STATIC_CSS.read_bytes()
            self._send(200, content, content_type="text/css; charset=utf-8")
            return

        if parsed.path == "/acceso":
            next_path = query_args.get("next", ["/buscar"])[0]
            self._send(200, _login_html(next_path=next_path))
            return

        if parsed.path == "/":
            self._redirect("/buscar")
            return

        if parsed.path == "/buscar":
            if not self._require_auth():
                return
            query = " ".join(query_args.get("q", [""])[0].split())[:120]
            error = None
            results: list[SearchResult] = []
            if query:
                try:
                    results = self.app.search(query)
                except Exception as exc:
                    error = f"No se pudo consultar el catálogo ({type(exc).__name__})."
                    print(f"Search error: {type(exc).__name__}: {exc}", flush=True)
            self._send(
                200,
                _search_html(
                    query=query,
                    results=results,
                    max_age_hours=self.app.max_age_hours,
                    error=error,
                ),
            )
            return

        if parsed.path == "/api/search":
            if not self._require_auth(api=True):
                return
            query = " ".join(query_args.get("q", [""])[0].split())[:120]
            try:
                raw_limit = int(query_args.get("limit", [str(self.app.result_limit)])[0])
            except ValueError:
                raw_limit = self.app.result_limit
            results = self.app.search(query, limit=max(1, min(raw_limit, 20))) if len(query) >= 2 else []
            payload = {
                "query": query,
                "count": len(results),
                "results": [result_to_dict(result) for result in results],
            }
            self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), content_type="application/json; charset=utf-8")
            return

        self._send(404, _page("No encontrado", "<section class='empty'><h1>404</h1><p>Ruta no encontrada.</p></section>"))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        content_length = min(int(self.headers.get("Content-Length", "0") or 0), 4096)
        body = self.rfile.read(content_length).decode("utf-8", errors="replace")
        form = parse_qs(body)

        if parsed.path == "/acceso":
            supplied = form.get("token", [""])[0]
            destination = form.get("next", ["/buscar"])[0]
            if not destination.startswith("/") or destination.startswith("//"):
                destination = "/buscar"
            if self.app.token_matches(supplied):
                secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
                cookie = (
                    f"{_COOKIE_NAME}={supplied}; Path=/; Max-Age=2592000; "
                    f"HttpOnly; SameSite=Lax{secure}"
                )
                self._redirect(destination, cookie=cookie)
            else:
                self._send(401, _login_html(error="Clave incorrecta.", next_path=destination))
            return

        if parsed.path == "/salir":
            cookie = f"{_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
            self._redirect("/acceso", cookie=cookie)
            return

        self._send(404, b"Not found", content_type="text/plain; charset=utf-8")


class SearchServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: SearchApplication):
        self.app = app
        super().__init__(address, SearchHandler)


def main() -> int:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    application = SearchApplication()
    server = SearchServer((host, port), application)
    print(
        f"Buscador v{APP_VERSION} escuchando en http://{host}:{port} · "
        f"auth={'configurada' if application.access_token else 'PENDIENTE'}.",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        application.engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
