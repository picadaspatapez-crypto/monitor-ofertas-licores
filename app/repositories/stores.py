from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Store


def get_or_create_store(
    session: Session,
    *,
    name: str,
    slug: str,
    base_url: str,
    connector_key: str,
    requires_browser: bool,
    country_code: str = "CL",
    currency_code: str = "CLP",
) -> Store:
    """Crea la tienda o sincroniza sus metadatos declarativos."""
    store = session.scalar(select(Store).where(Store.slug == slug))
    if store is None:
        store = Store(slug=slug)
        session.add(store)

    store.name = name
    store.base_url = base_url
    store.connector_key = connector_key
    store.is_active = True
    store.requires_browser = requires_browser
    store.country_code = country_code
    store.currency_code = currency_code
    session.flush()
    return store


def synchronize_active_stores(session: Session, connector_keys: set[str]) -> int:
    """Activa solo los collectors registrados y desactiva fuentes retiradas.

    Los productos históricos se conservan, pero las tiendas deshabilitadas dejan
    de participar en el buscador y en ofertas vigentes.
    """
    changed = 0
    stores = list(session.scalars(select(Store)).all())
    for store in stores:
        should_be_active = store.connector_key in connector_keys
        if bool(store.is_active) != should_be_active:
            store.is_active = should_be_active
            changed += 1
    session.flush()
    return changed
