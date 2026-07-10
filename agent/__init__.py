"""
agent/scrapers/__init__.py
Expone todos los scrapers como paquete importable desde agent/main.py

Scrapers activos:
  - scrape_local()        → Falabella, Ripley, Hiraoka (PEN)
  - scrape_dolar()        → USD/PEN tipo de cambio (5 fuentes + fallback)
  - get_exchange_rate()   → Tipo de cambio actual (para roi_calculator.py)
  - scrape_ebay()         → eBay Browse API USA (OAuth2)
  - scrape_camel()        → CamelCamelCamel RSS + historial ASIN
  - scrape_pcpartpicker() → PCPartPicker precios multi-tienda USA
  - scrape_kaggle()       → Datasets Kaggle (bulk histórico)
  - scrape_importacion()  → Precios de importación (Amazon, AliExpress, eBay)
  - scrape_competencia()  → Análisis de competencia local PE
"""

from .scraper_local        import scrape_local
from .scraper_dolar        import scrape_dolar, get_exchange_rate
from .scraper_ebay         import scrape_ebay
from .scraper_camel        import scrape_camel
from .scraper_pcpartpicker import scrape_pcpartpicker
from .scraper_kaggle       import scrape_kaggle

# FIX: scraper_importacion y scraper_competencia existen en el repo
# Se importan con try/except para no romper el paquete si aún no tienen
# su interfaz pública definida
try:
    from .scraper_importacion import scrape_importacion
    _HAS_IMPORTACION = True
except (ImportError, AttributeError):
    scrape_importacion = None
    _HAS_IMPORTACION   = False

try:
    from .scraper_competencia import scrape_competencia
    _HAS_COMPETENCIA = True
except (ImportError, AttributeError):
    scrape_competencia = None
    _HAS_COMPETENCIA   = False


__all__ = [
    # Scrapers principales — siempre disponibles
    "scrape_local",
    "scrape_dolar",
    "get_exchange_rate",
    "scrape_ebay",
    "scrape_camel",
    "scrape_pcpartpicker",
    "scrape_kaggle",
    # Scrapers opcionales — disponibles si el módulo está implementado
    "scrape_importacion",
    "scrape_competencia",
    # Flags de disponibilidad
    "_HAS_IMPORTACION",
    "_HAS_COMPETENCIA",
]
