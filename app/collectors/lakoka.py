from __future__ import annotations
import time
from urllib.parse import quote
from app.collectors.base import StoreMetadata
from app.collectors.http_catalog import discount, session
from app.deadlines import bounded_request_timeout, ensure_budget
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats

BASE_URL='https://www.lakoka.cl'
COLLECTIONS=(('licores','Licores'),('vinos','Vinos'),('espumantes','Espumantes'),('cervezas','Cervezas'))

def _money(v)->int|None:
    try:return int(round(float(str(v))))
    except (TypeError,ValueError):return None

def _collect()->CollectionBatch:
    started=time.monotonic();s=session();allp={};stats=[];pages=dups=0
    try:
      for handle,label in COLLECTIONS:
        ensure_budget(f'La Koka {label}'); sec_started=time.monotonic(); count=0;sp=0;status='success';err=None;seen_ids=set()
        try:
          page=1
          while page<=60:
            ensure_budget(f'La Koka {label} página {page}')
            url=f'{BASE_URL}/collections/{quote(handle)}/products.json?limit=250&page={page}'
            r=s.get(url,timeout=bounded_request_timeout((5,20)))
            if r.status_code>=400: raise RuntimeError(f'HTTP {r.status_code}')
            payload=r.json(); products=payload.get('products') if isinstance(payload,dict) else None
            if not isinstance(products,list): raise RuntimeError('JSON Shopify sin products[]')
            pages+=1;sp+=1
            if not products: break
            new=0
            for raw in products:
              pid=raw.get('id'); handlep=str(raw.get('handle') or '').strip(); title=str(raw.get('title') or '').strip()
              if not pid or not handlep or not title or pid in seen_ids: continue
              seen_ids.add(pid); variants=raw.get('variants') or []
              available=[v for v in variants if v.get('available',True) is not False]
              pool=available or variants
              priced=[(v,_money(v.get('price'))) for v in pool]; priced=[x for x in priced if x[1] and x[1]>0]
              if not priced: continue
              variant,current=min(priced,key=lambda x:x[1]); compare=_money(variant.get('compare_at_price')); regular=compare if compare and compare>current else None
              url=f'{BASE_URL}/products/{handlep}'
              incoming=CollectedProduct(store='La Koka',name=title[:500],url=url,current_price=current,regular_price=regular,discount_pct=discount(regular,current),source_sections=(label,),sku=(str(variant.get('sku') or '').strip() or None),ean=(str(variant.get('barcode') or '').strip() or None))
              old=allp.get(url)
              if old: dups+=1
              else:new+=1;count+=1
              if old is None or incoming.current_price<old.current_price: allp[url]=incoming
            if len(products)<250 or new==0: break
            page+=1
        except Exception as exc:
          status='failed';err=f'{type(exc).__name__}: {exc}'[:1000]
        stats.append(SectionStats(key=handle,name=label,url=f'{BASE_URL}/collections/{handle}',pages_visited=sp,cards_seen=count,unique_products=count,duration_ms=int((time.monotonic()-sec_started)*1000),status=status,error_message=err,structural_warning=(count==0)))
    finally:s.close()
    failed=sum(x.status!='success' for x in stats); warnings=sum(x.structural_warning for x in stats);score=max(0,min(100,100-failed*15-warnings*8));health='HEALTHY' if len(allp)>=100 and failed==0 and warnings==0 else ('DEGRADED' if len(allp)>=50 else 'BROKEN')
    cs=CollectionStats(pages_visited=pages,cards_seen=len(allp),unique_products=len(allp),sections_discovered=len(COLLECTIONS),sections_visited=len(stats),sections_succeeded=sum(x.status=='success' for x in stats),sections_failed=failed,duplicates_removed=dups,discovery_source='shopify_collection_products_json',health_status=health,health_score=score,structural_warnings=warnings,section_stats=tuple(stats),performance_ms={'total':int((time.monotonic()-started)*1000)})
    if not allp: raise RuntimeError('La Koka no entregó productos.')
    return CollectionBatch(products=list(allp.values()),stats=cs)
class LaKokaCollector:
    metadata=StoreMetadata(name='La Koka',slug='la-koka',base_url=f'{BASE_URL}/',connector_key='lakoka',requires_browser=False)
    key=metadata.connector_key;store_name=metadata.name
    def collect(self):return _collect()
