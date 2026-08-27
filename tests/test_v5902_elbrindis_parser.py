import pytest
from app.collectors.elbrindis import ElBrindisCollector
from app.collectors.http_catalog import parse_woocommerce_cards


def test_flatsome_woocommerce_cards_are_parsed_individually():
    html='''
    <div class="products row">
      <div class="product-small col"><div class="col-inner"><div class="product-small box">
        <div class="box-image"><a href="https://elbrindis.cl/producto/red"><img></a></div>
        <div class="box-text box-text-products"><p class="name product-title woocommerce-loop-product__title"><a href="https://elbrindis.cl/producto/red">Whisky Johnnie Walker Red Label 750cc</a></p>
        <span class="price"><del><span>$14.990</span></del><ins><span>$9.490</span></ins></span></div>
      </div></div></div>
      <div class="product-small col"><div class="col-inner"><div class="product-small box">
        <div class="box-image"><a href="https://elbrindis.cl/producto/black"><img></a></div>
        <div class="box-text box-text-products"><p class="name product-title woocommerce-loop-product__title"><a href="https://elbrindis.cl/producto/black">Whisky Johnnie Walker Black Label 750cc</a></p>
        <span class="price"><del><span>$36.990</span></del><ins><span>$24.490</span></ins></span></div>
      </div></div></div>
    </div>'''
    products,cards=parse_woocommerce_cards(html,store_name='El Brindis',base_url='https://elbrindis.cl',section_name='Whisky')
    assert cards==2 and len(products)==2
    by_name={p.name:p for p in products.values()}
    assert by_name['Whisky Johnnie Walker Red Label 750cc'].current_price==9490
    assert by_name['Whisky Johnnie Walker Red Label 750cc'].regular_price==14990
    assert by_name['Whisky Johnnie Walker Black Label 750cc'].current_price==24490


def test_parser_fails_closed_when_many_product_links_collapse_to_one_card():
    links=''.join(f'<a href="https://elbrindis.cl/producto/p{i}">Producto {i}</a>' for i in range(8))
    html=f'<div class="bad-grid">{links}<span>$9.990</span></div>'
    with pytest.raises(RuntimeError,match='parser WooCommerce no confiable'):
        parse_woocommerce_cards(html,store_name='El Brindis',base_url='https://elbrindis.cl',section_name='Whisky')


def test_elbrindis_uses_http_and_specialized_parser_configuration():
    assert ElBrindisCollector.metadata.requires_browser is False
    # Smoke test that the collector remains registered around the public HTTP catalog design.
    assert ElBrindisCollector.key=='elbrindis'
