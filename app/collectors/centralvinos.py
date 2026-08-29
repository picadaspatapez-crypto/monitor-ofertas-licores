from __future__ import annotations
from urllib.parse import urlencode,urlparse
from bs4 import BeautifulSoup,Tag
from app.collectors.base import StoreMetadata
from app.collectors.http_catalog import HtmlCatalogSection, collect_html_store, canonical, prices, text, fold, discount
from app.domain import CollectedProduct
BASE_URL='https://www.centralvinosylicores.cl'
SECTIONS=tuple(HtmlCatalogSection(k,n,f'/{p}') for k,n,p in (
 ('whisky','Whisky','whisky'),('pisco','Pisco','pisco'),('ron','Ron','ron'),('tequila','Tequila','tequila'),('vodka','Vodka','vodka'),('licores','Licores','licores'),('vinos','Vinos','vinos'),('espumante','Espumante','espumante')))
EXCLUDED={'','whisky','pisco','ron','tequila','vodka','licores','vinos','espumante','premium','cerveza','ofertas','bebidas','accesorios','contacto','contact','cart','carro','search','buscar','account','login'}
def _page(base,sec,page): return f'{base}{sec.path}' if page<=1 else f'{base}{sec.path}?{urlencode({"page":page})}'
def _is_product(href):
    p=urlparse(canonical(BASE_URL,href)); parts=[x for x in p.path.split('/') if x]
    return (len(parts)==1 and parts[0].casefold() not in EXCLUDED) or (len(parts)==2 and parts[0].casefold() in {'product','products','producto','productos'})
def _parse(html,*,store_name,base_url,section_name,product_path_markers):
    soup=BeautifulSoup(html,'html.parser'); out={}; candidates=0
    for h in soup.select('h2,h3,h4'):
        if not isinstance(h,Tag): continue
        name=text(h.get_text(' ',strip=True)); a=h.find('a',href=True) or h.find_parent('a',href=True)
        if not isinstance(a,Tag) or len(name)<4 or not _is_product(str(a.get('href') or '')): continue
        card=h
        for parent in h.parents:
            if not isinstance(parent,Tag) or parent.name in {'body','html','[document]'}: break
            links={canonical(base_url,str(x.get('href') or '')) for x in parent.select('a[href]') if _is_product(str(x.get('href') or ''))}
            if len(links)>1: break
            card=parent
            if len(links)==1 and prices(text(parent.get_text(' ',strip=True))): break
        vals=prices(text(card.get_text(' ',strip=True)))
        if not vals: continue
        current=vals[-1]; higher=[v for v in vals[:-1] if v>current]; regular=max(higher) if higher else None
        candidates+=1; f=fold(text(card.get_text(' ',strip=True)))
        if any(x in f for x in ('agotado','sin stock','no disponible')): continue
        url=canonical(base_url,str(a.get('href') or ''))
        out[url]=CollectedProduct(store=store_name,name=name[:500],url=url,current_price=current,regular_price=regular,discount_pct=discount(regular,current),source_sections=(section_name,))
    return out,candidates
class CentralVinosCollector:
    metadata=StoreMetadata(name='Central Vinos y Licores',slug='central-vinos-y-licores',base_url=f'{BASE_URL}/',connector_key='centralvinos',requires_browser=False)
    key=metadata.connector_key; store_name=metadata.name
    def collect(self): return collect_html_store(store_name=self.store_name,base_url=BASE_URL,sections=SECTIONS,page_url=_page,max_pages=80,min_products=150,product_path_markers=('/',),card_parser=_parse)
