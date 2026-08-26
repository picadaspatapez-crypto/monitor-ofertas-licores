from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.repositories.matching import products_observed_in_runs


def test_products_observed_query_avoids_distinct_over_json_columns(monkeypatch):
    captured = {}

    class DummyScalars:
        def __iter__(self):
            return iter(())

    def fake_scalars(self, statement):
        captured['statement'] = statement
        return DummyScalars()

    monkeypatch.setattr(Session, 'scalars', fake_scalars)
    session = object.__new__(Session)
    assert products_observed_in_runs(session, [1, 2]) == []

    sql = str(captured['statement'].compile(
        dialect=postgresql.dialect(),
        compile_kwargs={'literal_binds': True},
    )).upper()
    assert 'SELECT DISTINCT' not in sql
    assert 'EXISTS' in sql
    assert 'PRICE_OBSERVATIONS' in sql
