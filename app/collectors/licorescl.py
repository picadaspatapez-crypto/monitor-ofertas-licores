from __future__ import annotations
import re
from bs4 import BeautifulSoup,Tag
from urllib.parse import urlencode
from app.collectors.base import StoreMetadata
from app.collectors.http_catalog import HtmlCatalogSection, collect_html_store, canonical, prices, text, fold, discount
from app.domain import CollectedProduct
BASE_URL='https://www.licores.cl'
# IDs públicos confirmados en el menú del catálogo.
SECTIONS=tuple(HtmlCatalogSection(k,n,f'/producto/listado?categoria_id={cid}') for k,n,cid in (
 ('vino','Vino',4),('espumante','Vino Espumante',14),('whisky','Whisky',3),('gin','Gin',9),('pisco','Pisco',6),('ron','Ron',8),('tequila','Tequila',2),('vodka','Vodka',5)))
def _page(base,sec,page):
    sep='&' if '?' in sec.path else '?'
    return f'{base}{sec.path}' if page<=1 else f'{base}{sec.path}{sep}{urlencode({"page":page,"per-page":12})}'
def _parse(html,*,store_name,base_url,section_name,product_path_markers):
    soup=BeautifulSoup(html,'html.parser'); out={}; candidates=0
    anchors={}
    for a in soup.select('a[href*="/producto/detalle"]'):
        if not isinstance(a,Tag): continue
        name=text(a.get_text(' ',strip=True))
        if len(name)<5 or name.startswith('$'): continue
        url=canonical(base_url,str(a.get('href') or '')); anchors[url]=(a,name)
    for url,(a,name) in anchors.items():
        card=a
        for parent in a.parents:
            if not isinstance(parent,Tag) or parent.name in {'body','html','[document]'}: break
            card=parent
            detail={canonical(base_url,str(x.get('href') or '')) for x in parent.select('a[href*="/producto/detalle"]')}
            if len(detail)>1: break
            if prices(text(parent.get_text(' ',strip=True))):
                classes=' '.join(parent.get('class') or []).lower()
                if parent.name in {'li','article','div'} and any(x in classes for x in ('product','item','card','col')): break
        allvals=prices(text(card.get_text(' ',strip=True)))
        if not allvals: continue
        delvals=[]
        for d in card.select('del'): delvals.extend(prices(text(d.get_text(' ',strip=True))))
        non_del=[v for v in allvals if v not in delvals]
        current=non_del[-1] if non_del else allvals[-1]
        regular=max([v for v in delvals if v>current],default=None)
        candidates+=1
        f=fold(text(card.get_text(' ',strip=True)))
        if any(x in f for x in ('agotado','sin stock','sin existencias')): continue
        out[url]=CollectedProduct(store=store_name,name=name[:500],url=url,current_price=current,regular_price=regular,discount_pct=discount(regular,current),source_sections=(section_name,))
    return out,candidates
class LicoresClCollector:
    metadata=StoreMetadata(name='Licores.cl',slug='licores-cl',base_url=f'{BASE_URL}/',connector_key='licorescl',requires_browser=False)
    key=metadata.connector_key; store_name=metadata.name
    def collect(self): return collect_html_store(store_name=self.store_name,base_url=BASE_URL,sections=SECTIONS,page_url=_page,max_pages=80,min_products=100,product_path_markers=('/producto/detalle',),card_parser=_parse)
