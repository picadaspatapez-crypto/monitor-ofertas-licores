from __future__ import annotations
from app.collectors.base import StoreMetadata
from app.collectors.http_catalog import HtmlCatalogSection, collect_html_store, parse_woocommerce_cards

BASE_URL='https://vinoslareina.cl'
SECTIONS=tuple(HtmlCatalogSection(k,n,f'/categoria-producto/{p}/') for k,n,p in (
 ('vinos','Vinos','vinos'),('espumantes','Espumantes','espumantes'),('destilados','Destilados','destilados'),('cervezas','Cervezas','cervezas')))
def _page(base,sec,page): return f'{base}{sec.path}' if page<=1 else f'{base}{sec.path}page/{page}/'
class VinosLaReinaCollector:
    metadata=StoreMetadata(name='Tienda de Vinos La Reina',slug='vinos-la-reina',base_url=f'{BASE_URL}/',connector_key='vinoslareina',requires_browser=False)
    key=metadata.connector_key; store_name=metadata.name
    def collect(self):
        return collect_html_store(store_name=self.store_name,base_url=BASE_URL,sections=SECTIONS,page_url=_page,max_pages=80,min_products=150,product_path_markers=('/producto/',),card_parser=parse_woocommerce_cards,terminal_404_after_success=True)
