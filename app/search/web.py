from __future__ import annotations

import hmac
import html
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from sqlalchemy import func, select, text

from app.database import create_database
from app.models import Product, Store
from app.search.engine import SearchResult, search_products
from app.search.formatting import format_clp, format_datetime_cl, result_to_dict
from app.version import APP_VERSION, RELEASE_NAME


_COOKIE_NAME = "liquor_search_access"
_STATIC_CSS = Path(__file__).with_name("static") / "search.css"


@dataclass(frozen=True)
class CatalogPulse:
    public_stores: int = 0
    personal_sources: int = 0
    comparable_products: int = 0
    fresh_offers: int = 0


def _positive_int(name: str, default: int, *, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} debe ser un número entero.") from exc
    if value < 1:
        raise RuntimeError(f"{name} debe ser mayor que cero.")
    return min(value, maximum) if maximum is not None else value


def _format_count(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def _page(title: str, body: str) -> bytes:
    document = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0b0f15">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="/static/search.css">
</head>
<body>
  <div class="ambient ambient-one" aria-hidden="true"></div>
  <div class="ambient ambient-two" aria-hidden="true"></div>
  <main class="shell">{body}</main>
</body>
</html>"""
    return document.encode("utf-8")


def _brand_mark() -> str:
    return """<div class="brand-mark" aria-hidden="true"><span></span><span></span><span></span></div>"""


def _login_html(*, error: str | None = None, next_path: str = "/buscar") -> bytes:
    error_html = f'<div class="error" role="alert">{html.escape(error)}</div>' if error else ""
    body = f"""
<section class="auth-wrap">
  <div class="auth-brand">{_brand_mark()}<div><strong>Monitor de Licores</strong><span>Comparador privado</span></div></div>
  <section class="panel compact">
    <div class="eyebrow">Acceso privado · v{APP_VERSION}</div>
    <h1 class="auth-title">Entra a tu catálogo</h1>
    <p>Usa la clave privada configurada en Railway para acceder al buscador.</p>
    {error_html}
    <form method="post" action="/acceso" class="stack">
      <input type="hidden" name="next" value="{html.escape(next_path, quote=True)}">
      <label for="token">Clave de acceso</label>
      <input id="token" name="token" type="password" autocomplete="current-password" required autofocus placeholder="••••••••••••">
      <button type="submit">Entrar al comparador</button>
    </form>
  </section>
</section>"""
    return _page("Acceso · Monitor de Licores", body)


def _setup_html() -> bytes:
    body = f"""
<section class="auth-wrap">
  <div class="auth-brand">{_brand_mark()}<div><strong>Monitor de Licores</strong><span>Comparador privado</span></div></div>
  <section class="panel compact">
    <div class="eyebrow">Configuración · v{APP_VERSION}</div>
    <h1 class="auth-title">Falta una variable</h1>
    <p>Agrega <code>SEARCH_ACCESS_TOKEN</code> al servicio web de Railway y vuelve a desplegarlo.</p>
    <p class="muted">Los collectors y el cron pueden seguir funcionando con normalidad.</p>
  </section>
</section>"""
    return _page("Configuración pendiente", body)


def _opportunity_class(score: float | None) -> str:
    if score is None:
        return ""
    if score >= 90:
        return " opportunity-excellent"
    if score >= 80:
        return " opportunity-great"
    if score >= 70:
        return " opportunity-good"
    return ""


def _price_context_label(offer) -> str:
    if offer.price_type == "MEMBER":
        return "Precio socio"
    if offer.price_type == "SALE":
        return "Oferta"
    return "Precio público"


def _result_html(result: SearchResult) -> str:
    meta: list[str] = []
    if result.brand:
        meta.append(f"<span>{html.escape(result.brand)}</span>")
    if result.variant:
        meta.append(f"<span>{html.escape(result.variant)}</span>")
    if result.volume_ml:
        meta.append(f"<span>{result.volume_ml} ml</span>")
    if result.package_quantity > 1:
        meta.append(f"<span>Pack {result.package_quantity}</span>")

    badges = [f'<span class="badge badge-match">Coincidencia {result.score * 100:.0f}%</span>']
    if result.opportunity_score is not None:
        classification = html.escape(result.opportunity_classification or "Oportunidad")
        badges.append(
            f'<span class="badge badge-opportunity{_opportunity_class(result.opportunity_score)}">'
            f'{result.opportunity_score:.0f}/100 · {classification}</span>'
        )

    stats: list[str] = []
    if result.runner_up and result.saving_clp > 0:
        stats.append(
            '<div class="insight"><span>Ahorro vs. 2ª tienda</span>'
            f'<strong>{format_clp(result.saving_clp)}</strong>'
            f'<small>{result.saving_pct * 100:.1f}% menos</small></div>'
        )
    if result.avg_90d:
        delta = (result.winner.price - result.avg_90d) / result.avg_90d
        delta_label = f"{abs(delta) * 100:.1f}% {'bajo' if delta <= 0 else 'sobre'} promedio"
        stats.append(
            '<div class="insight"><span>Promedio 90 días</span>'
            f'<strong>{format_clp(round(result.avg_90d))}</strong>'
            f'<small>{delta_label}</small></div>'
        )
    if result.min_90d:
        stats.append(
            '<div class="insight"><span>Mínimo 90 días</span>'
            f'<strong>{format_clp(result.min_90d)}</strong>'
            '<small>historial reciente</small></div>'
        )
    elif result.historical_min:
        stats.append(
            '<div class="insight"><span>Mínimo histórico</span>'
            f'<strong>{format_clp(result.historical_min)}</strong>'
            '<small>desde el monitoreo</small></div>'
        )

    offers: list[str] = []
    for index, offer in enumerate(result.offers, start=1):
        best = " best" if offer.product_id == result.winner.product_id else ""
        regular = (
            f'<del>{format_clp(offer.regular_price)}</del>'
            if offer.regular_price and offer.regular_price > offer.price
            else ""
        )
        best_badge = '<span class="best-label">Mejor precio</span>' if best else ""
        context_badge = (
            f'<span class="context-label member">{_price_context_label(offer)}</span>'
            if offer.price_type == "MEMBER"
            else (f'<span class="context-label">{_price_context_label(offer)}</span>' if result.price_mode == "personal" else "")
        )
        offers.append(
            f"""<div class="offer{best}">
<div class="offer-rank">{index}</div>
<div class="offer-copy"><div class="offer-store"><strong>{html.escape(offer.store_name)}</strong>{best_badge}{context_badge}</div>
<p>{html.escape(offer.product_name)}</p>
<small>Actualizado {html.escape(format_datetime_cl(offer.last_seen_at))}</small></div>
<div class="offer-price">{regular}<strong>{format_clp(offer.price)}</strong>
<a class="store-link" href="{html.escape(offer.url, quote=True)}" target="_blank" rel="noopener noreferrer">Ver en tienda <span aria-hidden="true">↗</span></a></div>
</div>"""
        )

    store_count = len(result.offers)
    stores_label = "1 tienda" if store_count == 1 else f"{store_count} tiendas"
    if result.price_mode == "personal" and result.personal_advantage_clp > 0:
        stats.insert(0, '<div class="insight personal-insight"><span>Ahorro por membresía</span>'
            f'<strong>{format_clp(result.personal_advantage_clp)}</strong>'
            f'<small>{result.personal_advantage_pct * 100:.1f}% vs mejor precio público</small></div>')
    insights_html = f'<div class="insights">{"".join(stats)}</div>' if stats else ""
    winner_label = "Mejor precio para ti" if result.price_mode == "personal" else "Mejor precio público"

    return f"""<article class="result-card">
<div class="result-topline"><div class="badges">{''.join(badges)}</div><span class="store-count">{stores_label}</span></div>
<div class="result-head">
  <div class="result-title">
    <h2>{html.escape(result.canonical_name)}</h2>
    <div class="meta">{''.join(meta)}</div>
  </div>
  <div class="winner">
    <span>{winner_label}</span>
    <strong>{format_clp(result.winner.price)}</strong>
    <small>{html.escape(result.winner.store_name)}</small>
  </div>
</div>
{insights_html}
<div class="offers-head"><span>Comparación por tienda</span><span>De menor a mayor precio</span></div>
<div class="offers">{''.join(offers)}</div>
</article>"""


def _pulse_html(pulse: CatalogPulse | None, max_age_hours: int, price_mode: str = "public") -> str:
    if pulse is None:
        return ""
    return f"""<section class="pulse" aria-label="Estado del catálogo">
<div><strong>{_format_count(pulse.public_stores)}</strong><span>tiendas públicas</span></div>
<div><strong>{_format_count(pulse.personal_sources)}</strong><span>fuentes personales</span></div>
<div><strong>{_format_count(pulse.comparable_products)}</strong><span>productos comparables</span></div>
<div><strong>{_format_count(pulse.fresh_offers)}</strong><span>precios vigentes</span></div>
</section>"""


def _empty_home_html(pulse: CatalogPulse | None, max_age_hours: int, price_mode: str = "public") -> str:
    mode_query = "&mode=personal" if price_mode == "personal" else ""
    return f"""
{_pulse_html(pulse, max_age_hours, price_mode)}
<section class="quick-section">
  <div class="section-heading"><div><span class="eyebrow">Búsquedas rápidas</span><h2>Prueba el comparador</h2></div><p>Nombre, marca, variante y volumen funcionan juntos.</p></div>
  <div class="quick-links">
    <a href="/buscar?q=johnnie+black+750{mode_query}">Johnnie Black 750</a>
    <a href="/buscar?q=jack+honey{mode_query}">Jack Honey</a>
    <a href="/buscar?q=mistral+35+1+litro{mode_query}">Mistral 35° 1 litro</a>
    <a href="/buscar?q=gin+700{mode_query}">Gin 700 ml</a>
  </div>
</section>
<section class="feature-grid">
  <article><span class="feature-number">01</span><h3>Compara tiendas</h3><p>Agrupa publicaciones equivalentes y ordena sus precios de menor a mayor.</p></article>
  <article><span class="feature-number">02</span><h3>Mira el historial</h3><p>Contrasta el precio actual con mínimos y promedios observados por el monitor.</p></article>
  <article><span class="feature-number">03</span><h3>Detecta oportunidades</h3><p>El Opportunity Score resume precio, historial, matching y frescura del catálogo.</p></article>
</section>"""


def _search_html(
    *,
    query: str,
    results: list[SearchResult],
    max_age_hours: int,
    pulse: CatalogPulse | None = None,
    error: str | None = None,
    price_mode: str = "public",
) -> bytes:
    error_html = f'<div class="error" role="alert">{html.escape(error)}</div>' if error else ""
    content = ""
    if query and not results and not error:
        content = """<section class="empty"><div class="empty-icon">⌕</div><h2>No encontré coincidencias</h2>
<p>Prueba con menos palabras, otra variante del nombre o sin indicar el volumen.</p></section>"""
    elif query:
        noun = "coincidencia" if len(results) == 1 else "coincidencias"
        content = f"""<div class="results-summary"><div><strong>{len(results)}</strong> {noun} para <span>“{html.escape(query)}”</span></div>
<small>{'Con membresía CAV' if price_mode == 'personal' else 'Mercado público'} · precios observados en las últimas {max_age_hours} h</small></div>
<section class="results">{''.join(_result_html(item) for item in results)}</section>"""
    else:
        content = _empty_home_html(pulse, max_age_hours, price_mode)

    personal_active = price_mode == "personal"
    mode_hidden = '<input type="hidden" name="mode" value="personal">' if personal_active else ''
    public_href = "/buscar" + (("?q=" + urlencode({"q": query})[2:]) if query else "")
    personal_href = "/buscar?" + urlencode({"q": query, "mode": "personal"}) if query else "/buscar?mode=personal"
    body = f"""
<nav class="topbar">
  <a class="brand" href="/buscar" aria-label="Monitor de Licores, inicio">{_brand_mark()}<span><strong>Monitor de Licores</strong><small>Catálogo unificado · v{APP_VERSION}</small></span></a>
  <div class="top-actions"><div class="mode-switch"><a class="{'active' if not personal_active else ''}" href="{public_href}">Mercado público</a><a class="{'active personal' if personal_active else ''}" href="{personal_href}">Con membresía CAV</a></div><form method="post" action="/salir"><button class="ghost" type="submit">Salir</button></form></div>
</nav>
<header class="hero">
  <div class="hero-copy">
    <div class="eyebrow">Comparador de precios · Chile</div>
    <h1>Busca una botella.<br><span>Encuentra el mejor precio.</span></h1>
    <p>Compara publicaciones equivalentes entre las tiendas monitoreadas, con historial y Opportunity Score.</p>
  </div>
</header>
<form class="searchbar" method="get" action="/buscar" role="search">
  <span class="search-icon" aria-hidden="true">⌕</span>
  {mode_hidden}
  <input name="q" value="{html.escape(query, quote=True)}" placeholder="Ej: Johnnie Walker Black 750 ml" maxlength="120" aria-label="Buscar producto" autofocus>
  <button type="submit">Buscar <span aria-hidden="true">→</span></button>
</form>
{error_html}
{content}
<footer><span>Monitor de Licores · {html.escape(RELEASE_NAME)}</span><span>{'Incluye precios socio elegibles; el mercado público sigue separado.' if personal_active else 'Solo se comparan precios públicos y vigentes.'}</span></footer>"""
    return _page("Buscar precios · Monitor de Licores", body)


class SearchApplication:
    def __init__(self) -> None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("Falta la variable obligatoria: DATABASE_URL")
        self.access_token = os.getenv("SEARCH_ACCESS_TOKEN", "").strip()
        self.result_limit = _positive_int("SEARCH_RESULT_LIMIT", 8, maximum=30)
        self.max_age_hours = _positive_int("SEARCH_MAX_AGE_HOURS", 72, maximum=24 * 30)
        self.personal_price_audiences = tuple(
            value.strip().casefold() for value in os.getenv("PERSONAL_PRICE_AUDIENCES", "cav_member").split(",") if value.strip()
        )
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

    def search(
        self, query: str, *, limit: int | None = None, offset: int = 0, price_mode: str = "public"
    ) -> list[SearchResult]:
        with self.SessionLocal() as session:
            return search_products(
                session,
                query,
                limit=limit or self.result_limit,
                offset=offset,
                max_age_hours=self.max_age_hours,
                price_mode=price_mode,
                eligible_audiences=self.personal_price_audiences,
            )

    def catalog_pulse(self) -> CatalogPulse:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_age_hours)
        with self.SessionLocal() as session:
            public_filter = (
                Store.is_active.is_(True),
                Store.comparison_enabled.is_(True),
            )
            public_stores = int(
                session.scalar(select(func.count(Store.id)).where(*public_filter)) or 0
            )
            personal_sources = int(
                session.scalar(select(func.count(Store.id)).where(
                    Store.is_active.is_(True), Store.personal_comparison_enabled.is_(True)
                )) or 0
            )
            product_filter = (
                *public_filter,
                Product.is_available.is_(True),
                Product.current_price > 0,
                Product.last_seen_at >= cutoff,
            )
            fresh_offers = int(
                session.scalar(
                    select(func.count(Product.id))
                    .join(Store, Product.store_id == Store.id)
                    .where(*product_filter)
                )
                or 0
            )
            comparable_products = int(
                session.scalar(
                    select(func.count(func.distinct(Product.master_product_id)))
                    .join(Store, Product.store_id == Store.id)
                    .where(*product_filter, Product.master_product_id.is_not(None))
                )
                or 0
            )
        return CatalogPulse(
            public_stores=public_stores,
            personal_sources=personal_sources,
            comparable_products=comparable_products,
            fresh_offers=fresh_offers,
        )


class SearchHandler(BaseHTTPRequestHandler):
    server_version = "LiquorSearch/5.6.0"

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
            price_mode = "personal" if query_args.get("mode", ["public"])[0].casefold() == "personal" else "public"
            error = None
            results: list[SearchResult] = []
            pulse: CatalogPulse | None = None
            try:
                if query:
                    results = self.app.search(query, price_mode=price_mode)
                else:
                    pulse = self.app.catalog_pulse()
            except Exception as exc:
                if query:
                    error = f"No se pudo consultar el catálogo ({type(exc).__name__})."
                    print(f"Search error: {type(exc).__name__}: {exc}", flush=True)
                else:
                    print(f"Catalog pulse error: {type(exc).__name__}: {exc}", flush=True)
            self._send(
                200,
                _search_html(
                    query=query,
                    results=results,
                    max_age_hours=self.app.max_age_hours,
                    pulse=pulse,
                    error=error,
                    price_mode=price_mode,
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
            price_mode = "personal" if query_args.get("mode", ["public"])[0].casefold() == "personal" else "public"
            results = self.app.search(query, limit=max(1, min(raw_limit, 20)), price_mode=price_mode) if len(query) >= 2 else []
            payload = {
                "query": query,
                "count": len(results),
                "mode": price_mode,
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
