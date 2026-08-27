from __future__ import annotations
from app.collectors.base import StoreMetadata
from app.collectors.http_catalog import HtmlCatalogSection, collect_html_store
BASE_URL='https://elbrindis.cl'
SECTIONS=tuple(HtmlCatalogSection(k,n,f'/categoria-producto/{p}/') for k,n,p in (
('vinos','Vinos','vinos'),('espumantes','Espumantes','espumantes'),('cervezas','Cervezas','cervezas'),('aperitivos','Aperitivos','aperitivos'),('whisky','Whisky','whisky'),('gin','Gin','gin'),('pisco','Pisco','pisco'),('ron','Ron','ron'),('sour','Sour','sour'),('tequila','Tequila','tequila'),('vodka','Vodka','vodka'),('otros-licores','Otros licores','otros-licores')))
def _page(base,sec,page): return f'{base}{sec.path}' if page<=1 else f'{base}{sec.path}page/{page}/'
class ElBrindisCollector:
    metadata=StoreMetadata(name='El Brindis',slug='el-brindis',base_url=f'{BASE_URL}/',connector_key='elbrindis',requires_browser=False)
    key=metadata.connector_key;store_name=metadata.name
    def collect(self):return collect_html_store(store_name=self.store_name,base_url=BASE_URL,sections=SECTIONS,page_url=_page,max_pages=100,min_products=200,product_path_markers=('/producto/','/product/'))
