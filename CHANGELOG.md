"""Compatibilidad temporal: usar app.collectors.licor3b en código nuevo."""
from app.collectors.licor3b import Licor3BCollector, scrape
from app.domain import CollectedProduct

ScrapedProduct = CollectedProduct

__all__ = ["Licor3BCollector", "ScrapedProduct", "scrape"]
