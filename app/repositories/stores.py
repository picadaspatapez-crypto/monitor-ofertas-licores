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
) -> Store:
    store = session.scalar(select(Store).where(Store.slug == slug))
    if store is not None:
        return store

    store = Store(
        name=name,
        slug=slug,
        base_url=base_url,
        connector_key=connector_key,
        is_active=True,
        requires_browser=requires_browser,
        country_code="CL",
        currency_code="CLP",
    )
    session.add(store)
    session.flush()
    return store
