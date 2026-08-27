from app.collectors.elbrindis import ElBrindisCollector
from app.collectors.ranchowines import RanchoWinesCollector
from app.collectors.lakoka import LaKokaCollector
from app.collectors.http_catalog import parse_cards
from app.collectors.registry import enabled_collectors

def test_v590_collectors_registered():
    by={c.key:c for c in enabled_collectors()}
    assert {'lakoka','elbrindis','ranchowines'} <= set(by)
    assert all(not by[k].metadata.requires_browser for k in ('lakoka','elbrindis','ranchowines'))

def test_elbrindis_woocommerce_card_parser():
    html="""<li class="product"><a href="https://elbrindis.cl/producto/jw-black"><h2>Whisky Johnnie Walker Black Label 750cc</h2></a><del>$36.990</del><ins>$24.990</ins><a>Añadir al carrito</a></li>"""
    p,n=parse_cards(html,store_name='El Brindis',base_url='https://elbrindis.cl',section_name='Whisky',product_path_markers=('/producto/',))
    assert n==1; x=next(iter(p.values())); assert x.current_price==24990 and x.regular_price==36990

def test_rancho_card_parser():
    html="""<article><a href="/product/chivas"><h3>Whisky Chivas Regal 12 años 40° 750cc</h3></a><span>$ 28.990</span><s>$ 37.990</s><button>Agregar</button></article>"""
    p,n=parse_cards(html,store_name='Rancho Wines',base_url='https://www.rancho-wines.cl',section_name='Licores',product_path_markers=('/product/',))
    x=next(iter(p.values())); assert n==1 and x.current_price==28990 and x.regular_price==37990

def test_metadata_names():
    assert LaKokaCollector.store_name=='La Koka'
    assert ElBrindisCollector.store_name=='El Brindis'
    assert RanchoWinesCollector.store_name=='Rancho Wines'
