from app.collectors.vinoslareina import VinosLaReinaCollector
from app.collectors.licorescl import LicoresClCollector
from app.collectors.centralvinos import CentralVinosCollector

def test_wave2_collectors_are_http_only():
    for c in (VinosLaReinaCollector(), LicoresClCollector(), CentralVinosCollector()):
        assert c.metadata.requires_browser is False
        assert c.key == c.metadata.connector_key

def test_wave2_unique_keys():
    assert {VinosLaReinaCollector.key,LicoresClCollector.key,CentralVinosCollector.key} == {'vinoslareina','licorescl','centralvinos'}
