from __future__ import annotations
from urllib.parse import urlencode
from app.collectors.base import StoreMetadata
from app.collectors.http_catalog import HtmlCatalogSection, collect_html_store
BASE_URL='https://www.rancho-wines.cl'
SECTIONS=(HtmlCatalogSection('vinos','Vinos','/collection/vinos'),HtmlCatalogSection('espumantes','Espumantes','/collection/espumantes'),HtmlCatalogSection('licores','Licores','/collection/licores'))
def _page(base,sec,page): return f'{base}{sec.path}' if page<=1 else f'{base}{sec.path}?{urlencode({"page":page})}'
class RanchoWinesCollector:
    metadata=StoreMetadata(name='Rancho Wines',slug='rancho-wines',base_url=f'{BASE_URL}/',connector_key='ranchowines',requires_browser=False)
    key=metadata.connector_key;store_name=metadata.name
    def collect(self):return collect_html_store(store_name=self.store_name,base_url=BASE_URL,sections=SECTIONS,page_url=_page,max_pages=40,min_products=50,product_path_markers=('/product/','/products/'))
