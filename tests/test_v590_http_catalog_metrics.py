from app.performance import PhaseMetrics

def test_phase_metrics_api_used_by_http_catalog():
    from pathlib import Path
    source = Path('app/collectors/http_catalog.py').read_text()
    assert "metrics.add('download'" in source
    assert "metrics.add('parse'" in source
    assert 'metrics.download' not in source
    assert 'metrics.parse' not in source
    m=PhaseMetrics(); m.add('download', 7); m.add('parse', 3)
    assert m.as_dict()=={'download':7,'parse':3}
