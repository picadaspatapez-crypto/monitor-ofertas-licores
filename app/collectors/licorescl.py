from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from app.collectors.base import StoreMetadata
from app.collectors.http_catalog import HtmlCatalogSection, collect_html_store, discount, fold, prices, text
from app.domain import CollectedProduct

BASE_URL = 'https://www.licores.cl'

# IDs públicos confirmados en el menú del catálogo.
SECTIONS = tuple(
    HtmlCatalogSection(k, n, f'/producto/listado?categoria_id={cid}')
    for k, n, cid in (
        ('vino', 'Vino', 4),
        ('espumante', 'Vino Espumante', 14),
        ('whisky', 'Whisky', 3),
        ('gin', 'Gin', 9),
        ('pisco', 'Pisco', 6),
        ('ron', 'Ron', 8),
        ('tequila', 'Tequila', 2),
        ('vodka', 'Vodka', 5),
    )
)


def _page(base, sec, page):
    sep = '&' if '?' in sec.path else '?'
    return f'{base}{sec.path}' if page <= 1 else f'{base}{sec.path}{sep}{urlencode({"page": page, "per-page": 12})}'


def _detail_url(base_url: str, raw: str) -> str | None:
    """Canonicaliza una ficha de Licores.cl preservando el ``id`` del producto.

    El helper común ``canonical()`` elimina el query string deliberadamente. Eso es correcto
    para la mayoría de las tiendas, pero Licores.cl identifica *todas* sus fichas con la misma
    ruta ``/producto/detalle`` y el producto vive en ``?id=N``. Si se elimina ese query, todo el
    catálogo colapsa a una sola identidad.
    """
    p = urlparse(urljoin(base_url, raw))
    if p.path.rstrip('/') != '/producto/detalle':
        return None
    product_id = (parse_qs(p.query).get('id') or [''])[0].strip()
    if not product_id.isdigit():
        return None
    host = p.netloc.casefold().removeprefix('www.')
    return urlunparse(('https', host, '/producto/detalle', '', urlencode({'id': product_id}), ''))


def _detail_urls(node: Tag, base_url: str) -> set[str]:
    out: set[str] = set()
    for a in node.select('a[href*="/producto/detalle"]'):
        if not isinstance(a, Tag):
            continue
        url = _detail_url(base_url, str(a.get('href') or ''))
        if url:
            out.add(url)
    return out


def _nearest_product_card(anchor: Tag, *, base_url: str) -> Tag:
    fallback = anchor
    for parent in anchor.parents:
        if not isinstance(parent, Tag) or parent.name in {'body', 'html', '[document]'}:
            break
        detail_urls = _detail_urls(parent, base_url)
        if len(detail_urls) > 1:
            break
        fallback = parent
        if len(detail_urls) == 1 and prices(text(parent.get_text(' ', strip=True))):
            return parent
    return fallback


def _parse(html, *, store_name, base_url, section_name, product_path_markers):
    soup = BeautifulSoup(html, 'html.parser')
    out: dict[str, CollectedProduct] = {}
    candidates = 0
    anchors: dict[str, list[Tag]] = {}

    for a in soup.select('a[href*="/producto/detalle"]'):
        if not isinstance(a, Tag):
            continue
        url = _detail_url(base_url, str(a.get('href') or ''))
        if url:
            anchors.setdefault(url, []).append(a)

    for url, product_anchors in anchors.items():
        # El mismo producto puede tener enlace en foto, precio, título y "Ver detalle".
        # Preferimos el ancla cuyo texto parece realmente el nombre del producto.
        anchor = product_anchors[0]
        name = ''
        for candidate_anchor in product_anchors:
            candidate = text(candidate_anchor.get_text(' ', strip=True))
            f = fold(candidate)
            if len(candidate) >= 5 and not candidate.startswith('$') and f not in {'ver detalle', 'detalle', 'agregar'}:
                anchor = candidate_anchor
                name = candidate
                break

        card = _nearest_product_card(anchor, base_url=base_url)
        if not name:
            title_node = card.select_one('h1,h2,h3,h4,.product-name,.name,.title')
            if isinstance(title_node, Tag):
                name = text(title_node.get_text(' ', strip=True))
        if len(name) < 5:
            continue

        card_text = text(card.get_text(' ', strip=True))
        all_values = prices(card_text)
        if not all_values:
            continue

        # En Licores.cl el precio tachado no siempre es mayor que el vigente. Por eso no
        # inferimos "precio actual = mínimo". ``del`` es referencia/anterior; el precio fuera
        # de ``del`` es el vigente, aun cuando sea mayor.
        deleted_values: list[int] = []
        for d in card.select('del'):
            deleted_values.extend(prices(text(d.get_text(' ', strip=True))))
        live_values = list(all_values)
        for old in deleted_values:
            try:
                live_values.remove(old)
            except ValueError:
                pass
        current = live_values[-1] if live_values else all_values[-1]
        regular = max((v for v in deleted_values if v > current), default=None)

        candidates += 1
        f = fold(card_text)
        if any(x in f for x in ('agotado', 'sin stock', 'sin existencias')):
            continue

        out[url] = CollectedProduct(
            store=store_name,
            name=name[:500],
            url=url,
            current_price=current,
            regular_price=regular,
            discount_pct=discount(regular, current),
            source_sections=(section_name,),
        )

    # Fallar cerrado si una página expone muchas identidades pero el parser apenas produce
    # resultados. Evita volver a persistir un catálogo de una sola ficha por colapso de IDs.
    if len(anchors) >= 4 and len(out) < max(2, int(len(anchors) * 0.5)):
        raise RuntimeError(
            f'parser Licores.cl no confiable: ids_producto={len(anchors)}, productos_parseados={len(out)}'
        )
    return out, candidates


class LicoresClCollector:
    metadata = StoreMetadata(
        name='Licores.cl',
        slug='licores-cl',
        base_url=f'{BASE_URL}/',
        connector_key='licorescl',
        requires_browser=False,
    )
    key = metadata.connector_key
    store_name = metadata.name

    def collect(self):
        return collect_html_store(
            store_name=self.store_name,
            base_url=BASE_URL,
            sections=SECTIONS,
            page_url=_page,
            max_pages=80,
            min_products=100,
            product_path_markers=('/producto/detalle',),
            card_parser=_parse,
        )
