import os
import re
import sys
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup


OFFERS_URL = "https://licor3b.cl/product-category/ofertas/"


@dataclass
class Product:
    name: str
    url: str
    current_price: int
    regular_price: Optional[int]
    discount_pct: float


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Falta la variable obligatoria: {name}")
    return value


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def parse_clp(text: str) -> Optional[int]:
    """Convierte textos como '$ 23.990' o '23,990' a 23990."""
    if not text:
        return None
    numbers = re.sub(r"[^\d]", "", text)
    return int(numbers) if numbers else None


def calculate_discount(regular: Optional[int], current: int) -> float:
    if not regular or regular <= current:
        return 0.0
    return (regular - current) / regular


def scrape_licor3b_offers() -> list[Product]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/126 Safari/537.36"
        )
    }
    response = requests.get(OFFERS_URL, headers=headers, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    products: list[Product] = []

    # Estructura habitual de WooCommerce.
    cards = soup.select("li.product")

    for card in cards:
        title_node = card.select_one(
            "h2.woocommerce-loop-product__title, "
            ".woocommerce-loop-product__title, "
            ".product-title"
        )
        link_node = card.select_one("a.woocommerce-LoopProduct-link, a[href]")
        price_node = card.select_one(".price")

        if not title_node or not link_node or not price_node:
            continue

        name = " ".join(title_node.get_text(" ", strip=True).split())
        url = link_node.get("href", "").strip()

        regular_node = price_node.select_one("del .woocommerce-Price-amount, del")
        current_node = price_node.select_one("ins .woocommerce-Price-amount, ins")

        # Si no existe <ins>, se usa el último monto mostrado.
        if current_node:
            current_price = parse_clp(current_node.get_text(" ", strip=True))
        else:
            amounts = price_node.select(".woocommerce-Price-amount")
            candidate = amounts[-1].get_text(" ", strip=True) if amounts else price_node.get_text(" ", strip=True)
            current_price = parse_clp(candidate)

        regular_price = (
            parse_clp(regular_node.get_text(" ", strip=True))
            if regular_node
            else None
        )

        if not name or not url or current_price is None:
            continue

        products.append(
            Product(
                name=name,
                url=url,
                current_price=current_price,
                regular_price=regular_price,
                discount_pct=calculate_discount(regular_price, current_price),
            )
        )

    if not products:
        raise RuntimeError(
            "No se encontraron productos. La tienda pudo cambiar su estructura."
        )

    return products


def format_clp(value: int) -> str:
    return "$" + f"{value:,}".replace(",", ".")


def send_telegram_message(message: str) -> None:
    token = require_env("TELEGRAM_BOT_TOKEN")
    chat_id = require_env("TELEGRAM_CHAT_ID")
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"

    response = requests.post(
        endpoint,
        json={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()


def build_report(products: list[Product]) -> str:
    max_price = env_int("MAX_PRODUCT_PRICE", 30000)
    budget = env_int("TOTAL_BUDGET", 100000)
    max_units = env_int("MAX_UNITS_PER_PRODUCT", 3)
    min_discount = env_float("MIN_TARGET_MARGIN", 0.20)

    candidates = [
        product
        for product in products
        if product.current_price <= max_price
        and product.discount_pct >= min_discount
    ]
    candidates.sort(key=lambda item: item.discount_pct, reverse=True)

    if not candidates:
        return (
            "🔎 Revisión Licor3B completada\n\n"
            f"Productos encontrados: {len(products)}\n"
            "No se encontraron ofertas que cumplan los filtros actuales."
        )

    lines = [
        "🚨 Ofertas detectadas en Licor3B",
        "",
        f"Catálogo revisado: {len(products)} productos",
        f"Candidatos: {len(candidates)}",
        "",
    ]

    for index, product in enumerate(candidates[:8], start=1):
        affordable_units = min(
            max_units,
            budget // product.current_price,
        )
        investment = product.current_price * affordable_units

        lines.extend(
            [
                f"{index}. {product.name}",
                f"Precio: {format_clp(product.current_price)}",
                f"Descuento publicado: {product.discount_pct:.0%}",
                f"Compra posible: {affordable_units} un. ({format_clp(investment)})",
                product.url,
                "",
            ]
        )

    lines.append(
        "⚠️ Esta primera versión filtra por descuento publicado. "
        "Aún no calcula el margen real de reventa."
    )
    return "\n".join(lines)


def main() -> int:
    try:
        products = scrape_licor3b_offers()
        report = build_report(products)
        send_telegram_message(report)
        print(f"Proceso terminado. Productos encontrados: {len(products)}")
        return 0
    except Exception as exc:
        error_message = f"❌ Error en monitor Licor3B:\n{exc}"
        print(error_message, file=sys.stderr)
        try:
            send_telegram_message(error_message)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
