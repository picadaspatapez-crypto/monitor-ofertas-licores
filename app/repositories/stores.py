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
