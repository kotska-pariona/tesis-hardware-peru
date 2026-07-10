"""
agent/scrapers/__init__.py
Expone todos los scrapers como paquete importable desde agent/main.py
"""
from .scraper_local        import scrape_local
from .scraper_dolar        import scrape_dolar, get_exchange_rate
from .scraper_ebay         import scrape_ebay
from .scraper_camel        import scrape_camel
from .scraper_pcpartpicker import scrape_pcpartpicker
from .scraper_kaggle       import scrape_kaggle

__all__ = [
    "scrape_local",
    "scrape_dolar",
    "get_exchange_rate",
    "scrape_ebay",
    "scrape_camel",
    "scrape_pcpartpicker",
    "scrape_kaggle",
]
