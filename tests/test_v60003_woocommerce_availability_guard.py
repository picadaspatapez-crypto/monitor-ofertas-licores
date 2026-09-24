from __future__ import annotations

import pytest

from app.collectors.http_catalog import parse_woocommerce_cards


def _card(slug: str, name: str, price: str, *, sold_out: bool = False) -> str:
    availability = (
        f'<a class="button sold-out" href="https://vinoslareina.cl/producto/{slug}/">AGOTADO</a>'
        if sold_out
        else f'<a class="button add_to_cart_button" href="https://vinoslareina.cl/producto/{slug}/">Añadir al carrito</a>'
    )
    css = 'product outofstock' if sold_out else 'product instock'
    return f'''
    <li class="{css}">
      <a href="https://vinoslareina.cl/producto/{slug}/"><img alt=""></a>
      <h2 class="woocommerce-loop-product__title">
        <a href="https://vinoslareina.cl/producto/{slug}/">{name}</a>
      </h2>
      <span class="price"><span>{price}</span></span>
      {availability}
    </li>
    '''


def test_availability_guard_accepts_page_with_many_explicitly_sold_out_cards():
    active = ''.join(
        _card(f'activo-{i}', f'Espumante Activo {i}', f'$ {8+i}.990')
        for i in range(5)
    )
    sold_out = ''.join(
        _card(f'agotado-{i}', f'Espumante Agotado {i}', f'$ {9+i}.990', sold_out=True)
        for i in range(9)
    )
    html = f'<ul class="products columns-4">{active}{sold_out}</ul>'

    products, cards = parse_woocommerce_cards(
        html,
        store_name='Tienda de Vinos La Reina',
        base_url='https://vinoslareina.cl',
        section_name='Espumantes',
        product_path_markers=('/producto/',),
    )

    assert cards == 14
    assert len(products) == 5
    assert all('activo-' in url for url in products)
    assert not any('agotado-' in url for url in products)


def test_availability_guard_still_fails_closed_for_unparsed_active_cards():
    # Four valid active cards plus six product URLs collapsed into a structure with no
    # usable per-product price/title context. Sold-out recognition must not hide this.
    valid = ''.join(
        _card(f'valido-{i}', f'Producto Valido {i}', '$ 9.990')
        for i in range(4)
    )
    broken = ''.join(
        f'<a href="https://vinoslareina.cl/producto/roto-{i}/">Producto Roto {i}</a>'
        for i in range(6)
    )
    html = f'<ul>{valid}</ul><div class="bad-grid">{broken}<span>sin precio por tarjeta</span></div>'

    with pytest.raises(RuntimeError, match='activos_esperados=10'):
        parse_woocommerce_cards(
            html,
            store_name='Tienda de Vinos La Reina',
            base_url='https://vinoslareina.cl',
            section_name='Espumantes',
            product_path_markers=('/producto/',),
        )


def test_all_sold_out_page_is_valid_structure_but_yields_no_active_offers():
    html = '<ul>' + ''.join(
        _card(f'agotado-{i}', f'Producto Agotado {i}', '$ 7.990', sold_out=True)
        for i in range(6)
    ) + '</ul>'

    products, cards = parse_woocommerce_cards(
        html,
        store_name='Tienda de Vinos La Reina',
        base_url='https://vinoslareina.cl',
        section_name='Espumantes',
        product_path_markers=('/producto/',),
    )

    assert cards == 6
    assert products == {}
