from app.collectors.centralvinos import SECTIONS as CENTRAL_SECTIONS
from app.collectors.licorescl import _detail_url, _page, _parse, SECTIONS as LICORES_SECTIONS


def test_central_uses_live_espumantes_slug():
    paths = {s.key: s.path for s in CENTRAL_SECTIONS}
    assert paths['espumantes'] == '/espumantes'
    assert '/espumante' not in paths.values()


def test_licores_detail_identity_preserves_product_id():
    assert _detail_url('https://www.licores.cl', '/producto/detalle?id=21') == 'https://licores.cl/producto/detalle?id=21'
    assert _detail_url('https://www.licores.cl', '/producto/detalle?id=22') == 'https://licores.cl/producto/detalle?id=22'
    assert _detail_url('https://www.licores.cl', '/producto/detalle') is None


def test_licores_page_two_matches_public_pagination_contract():
    whisky = next(s for s in LICORES_SECTIONS if s.key == 'whisky')
    assert _page('https://www.licores.cl', whisky, 2).endswith('categoria_id=3&page=2&per-page=12')


def test_licores_parser_keeps_query_ids_distinct_and_uses_live_price():
    html = '''
    <section class="catalog">
      <div class="item product">
        <h3><del>$26.990</del> <a href="/producto/detalle?id=21">$29.990</a></h3>
        <a href="/producto/detalle?id=21">Whisky Johnnie Walker Black Label 40° 750cc.</a>
      </div>
      <div class="item product">
        <h3><del>$20.990</del> <a href="/producto/detalle?id=22">$19.590</a></h3>
        <a href="/producto/detalle?id=22">Whisky Jameson 43° 750cc.</a>
      </div>
    </section>
    '''
    products, cards = _parse(
        html,
        store_name='Licores.cl',
        base_url='https://www.licores.cl',
        section_name='Whisky',
        product_path_markers=('/producto/detalle',),
    )
    assert cards == 2
    assert set(products) == {
        'https://licores.cl/producto/detalle?id=21',
        'https://licores.cl/producto/detalle?id=22',
    }
    black = products['https://licores.cl/producto/detalle?id=21']
    jameson = products['https://licores.cl/producto/detalle?id=22']
    # Old/tachado price can be LOWER on this site; never treat "minimum" as current price.
    assert black.current_price == 29990
    assert black.regular_price is None
    assert jameson.current_price == 19590
    assert jameson.regular_price == 20990
