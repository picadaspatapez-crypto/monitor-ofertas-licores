from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.intelligence.title_guard import repair_licor3b_title_integrity
from app.models import MasterProduct, OpportunitySnapshot, Product, Store


def test_repairs_persisted_licor3b_polluted_name_and_master():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        store = Store(name="Licor3B", slug="licor3b", base_url="https://licor3b.cl", connector_key="licor3b")
        session.add(store)
        master = MasterProduct(canonical_name="3 Vinos Montes Alpha Cabernet Sauvignon 3 Vinos Marques De Casa Concha Cabernet Sauvignon 750 ml", normalized_key="polluted|750", package_quantity=1)
        session.add(master)
        session.flush()
        product = Product(
            store="Licor3B", store_id=store.id, master_product_id=master.id,
            name="3 Vinos Montes Alpha Cabernet Sauvignon 3 Vinos Marques De Casa Concha Cabernet Sauvignon 750 ml",
            url="https://licor3b.cl/product/vino-marques-de-casa-concha-cabernet-sauvignon-750-ml/",
            current_price=12990, regular_price=14990, discount_pct=0.13,
            package_quantity=1, data_quality_score=100, data_quality_status="CLEAN", excluded_from_comparison=False,
        )
        session.add(product)
        session.commit()

        summary = repair_licor3b_title_integrity(session)
        session.commit()
        assert summary.products_repaired == 1
        assert product.name == "vino marques de casa concha cabernet sauvignon 750 ml"
        assert "Montes Alpha" not in master.canonical_name
        assert "Casa Concha" in master.canonical_name
