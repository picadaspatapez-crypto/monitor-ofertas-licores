from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.deadlines import bounded_request_timeout, ensure_budget
from app.domain import CollectedProduct, CollectionBatch, CollectionStats, SectionStats
from app.performance import PhaseMetrics

_PRICE_RE = re.compile(r"\$\s*([\d.]+)")

@dataclass(frozen=True)
class HtmlCatalogSection:
    key: str
    name: str
    path: str


def session() -> requests.Session:
    s=requests.Session()
    retry=Retry(total=2,connect=1,read=1,backoff_factor=.5,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset({'GET'}),respect_retry_after_header=True,raise_on_status=False)
    s.mount('https://',HTTPAdapter(max_retries=retry,pool_connections=8,pool_maxsize=8))
    s.headers.update({'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36','Accept-Language':'es-CL,es;q=0.9'})
    return s


def text(v:str)->str: return ' '.join((v or '').replace('\xa0',' ').split())
def fold(v:str)->str:
    n=unicodedata.normalize('NFKD',v or '')
    return ''.join(c for c in n if not unicodedata.combining(c)).casefold()
def prices(v:str)->list[int]:
    out=[]
    for raw in _PRICE_RE.findall(v or ''):
        d=re.sub(r'\D','',raw)
        if d:
            x=int(d)
            if 100 <= x <= 20_000_000 and x not in out: out.append(x)
    return out
def discount(regular:int|None,current:int)->float:
    return (regular-current)/regular if regular and regular>current else 0.0

def canonical(base_url:str,raw:str)->str:
    p=urlparse(urljoin(base_url,raw)); path=re.sub(r'/+','/',p.path).rstrip('/') or '/'
    return urlunparse(('https',p.netloc.casefold().removeprefix('www.'),path,'','',''))

def parse_cards(html:str,*,store_name:str,base_url:str,section_name:str,product_path_markers:tuple[str,...]=('/product','/producto','/products/')) -> tuple[dict[str,CollectedProduct],int]:
    soup=BeautifulSoup(html,'html.parser'); out={}; candidates=0; seen=set()
    for heading in soup.select('h2,h3,h4,a.woocommerce-LoopProduct-link .woocommerce-loop-product__title'):
        if not isinstance(heading,Tag): continue
        name=text(heading.get_text(' ',strip=True))
        if len(name)<4: continue
        link=heading.find_parent('a',href=True)
        if not isinstance(link,Tag):
            link=heading.find('a',href=True) if heading.name!='a' else heading
        if not isinstance(link,Tag):
            # Search a bounded parent card.
            card=heading
            for parent in heading.parents:
                if not isinstance(parent,Tag) or parent.name in {'body','html','[document]'}: break
                card=parent
                links=parent.select('a[href]')
                if any(any(m in str(a.get('href') or '') for m in product_path_markers) for a in links):
                    if prices(text(parent.get_text(' ',strip=True))): break
            link=next((a for a in card.select('a[href]') if any(m in str(a.get('href') or '') for m in product_path_markers)),None)
        else:
            card=heading
            for parent in heading.parents:
                if not isinstance(parent,Tag) or parent.name in {'body','html','[document]'}: break
                if prices(text(parent.get_text(' ',strip=True))): card=parent; break
        if not isinstance(link,Tag): continue
        href=str(link.get('href') or '')
        if not any(m in href for m in product_path_markers): continue
        url=canonical(base_url,href)
        if url in seen: continue
        card_text=text(card.get_text(' ',strip=True)); vals=prices(card_text)
        if not vals: continue
        candidates+=1; seen.add(url)
        f=fold(card_text)
        if any(x in f for x in ('agotado','sin stock','out of stock')): continue
        current=min(vals); higher=[v for v in vals if v>current]; regular=max(higher) if higher else None
        out[url]=CollectedProduct(store=store_name,name=name[:500],url=url,current_price=current,regular_price=regular,discount_pct=discount(regular,current),source_sections=(section_name,))
    return out,candidates

def merge(a:CollectedProduct|None,b:CollectedProduct)->CollectedProduct:
    if a is None:return b
    sections=tuple(sorted(set(a.source_sections+b.source_sections),key=str.casefold)); chosen=b if b.current_price<=a.current_price else a
    return replace(chosen,source_sections=sections)

def collect_html_store(*,store_name:str,base_url:str,sections:tuple[HtmlCatalogSection,...],page_url,max_pages:int=80,min_products:int=20,product_path_markers:tuple[str,...]=('/product','/producto','/products/')) -> CollectionBatch:
    started=time.monotonic(); s=session(); allp={}; section_stats=[]; pages=cards=dups=0; aggregate=PhaseMetrics()
    try:
      for sec in sections:
        ensure_budget(f'{store_name} categoría {sec.name}'); ss=time.monotonic(); urls=set(); prev=None; sp=sc=sd=0; status='success'; err=None; warning=False; metrics=PhaseMetrics()
        try:
          for page in range(1,max_pages+1):
            ensure_budget(f'{store_name} {sec.name} página {page}')
            url=page_url(base_url,sec,page); t=time.monotonic(); r=s.get(url,timeout=bounded_request_timeout((5,18))); metrics.download += int((time.monotonic()-t)*1000)
            if r.status_code>=400: raise RuntimeError(f'HTTP {r.status_code} en {url}')
            t=time.monotonic(); pp,pc=parse_cards(r.text,store_name=store_name,base_url=base_url,section_name=sec.name,product_path_markers=product_path_markers); metrics.parse += int((time.monotonic()-t)*1000)
            sig=tuple(sorted(pp)); pages+=1;sp+=1;cards+=pc;sc+=pc
            if page>1 and (not sig or sig==prev): break
            prev=sig; new=0
            for u,p in pp.items():
              if u in urls: sd+=1
              else: urls.add(u);new+=1
              if u in allp:dups+=1
              allp[u]=merge(allp.get(u),p)
            print(f'{store_name} {sec.key} página {page}: HTTP={r.status_code}, tarjetas={pc}, productos={len(pp)}, nuevos={new}, sección={len(urls)}, global={len(allp)}',flush=True)
            if page==1 and pc==0: warning=True
            if not pp or new==0: break
        except Exception as exc:
          status='failed';err=f'{type(exc).__name__}: {exc}'[:1000];print(f'✖ {store_name} {sec.name}: {err}. Continúa.',flush=True)
        section_stats.append(SectionStats(key=sec.key,name=sec.name,url=page_url(base_url,sec,1),pages_visited=sp,cards_seen=sc,unique_products=len(urls),duplicates_removed=sd,duration_ms=int((time.monotonic()-ss)*1000),status=status,error_message=err,structural_warning=warning,performance_ms=metrics.as_dict()));aggregate.merge(metrics)
    finally:s.close()
    failed=sum(x.status!='success' for x in section_stats); warnings=sum(x.structural_warning for x in section_stats)
    score=max(0,min(100,100-failed*15-warnings*8)); health='HEALTHY' if len(allp)>=min_products and not failed and not warnings else ('DEGRADED' if len(allp)>=min_products and score>=55 else 'BROKEN')
    stats=CollectionStats(pages_visited=pages,cards_seen=cards,unique_products=len(allp),sections_discovered=len(sections),sections_visited=len(section_stats),sections_succeeded=sum(x.status=='success' for x in section_stats),sections_failed=failed,duplicates_removed=dups,discovery_source='fixed_public_categories_http',health_status=health,health_score=score,structural_warnings=warnings,section_stats=tuple(section_stats),performance_ms={**aggregate.as_dict(),'total':int((time.monotonic()-started)*1000)})
    if not allp: raise RuntimeError(f'{store_name} no entregó productos.')
    return CollectionBatch(products=list(allp.values()),stats=stats)
