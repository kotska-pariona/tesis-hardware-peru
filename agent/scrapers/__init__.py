"""
agent/scrapers/__init__.py  v3.1
Expone todos los scrapers como paquete importable desde agent/main.py

CAMBIOS v3.1 (sobre v3.0):
  [I7] ebaysdk eliminado de pip install en ambos workflows → comentario [I1]
       actualizado: scrape_ebay usa OAuth2 directo con requests, no ebaysdk
  [I8] scraper_mercadolibre + scraper_newegg movidos de importlib a try/except
       (ambos archivos existen en el repo — importlib era innecesario)
  [I9] _HAS_MERCADOLIBRE + _HAS_NEWEGG agregados como flags de disponibilidad
       (consistencia con patrón _HAS_* del resto de scrapers opcionales)

Scrapers activos (confirmado en log batch_20260711_160344):
  - scrape_local()          → Falabella, Hiraoka (PEN)
  - scrape_dolar()          → USD/PEN tipo de cambio (cascada 3 fuentes)
  - get_exchange_rate()     → Tipo de cambio actual (para roi_calculator.py)
  - scrape_importacion()    → Precios de importación (Amazon USA activo)
  - scrape_competencia()    → Análisis competencia local PE (Falabella activo)
  - scrape_ebay()           → eBay Browse API USA — 14,760 registros ✅

Scrapers con try/except (opcionales — 0 resultados en log):
  - scrape_mercadolibre()   → MeLi PE API pública (0 resultados — revisar endpoint)
  - scrape_newegg()         → Newegg USA HTML scraping (0 resultados — revisar HTML)
  - scrape_camel()          → CamelCamelCamel RSS + historial ASIN
  - scrape_pcpartpicker()   → PCPartPicker precios multi-tienda USA
  - scrape_kaggle()         → Datasets Kaggle (bulk histórico)

Patrón de resiliencia:
  - import directo  → scraper CORE, siempre debe existir y funcionar
  - try/except      → scraper OPCIONAL, puede fallar sin romper el paquete
  - importlib       → NO USADO — todos los scrapers conocidos usan try/except
"""

# ── Scrapers CORE — siempre disponibles ────────────────────────────────────
# Si alguno falla aquí, el pipeline entero debe fallar (son dependencias duras)
from .scraper_local import scrape_local
from .scraper_dolar import scrape_dolar, get_exchange_rate

# ── Scrapers OPCIONALES — try/except para no romper el paquete ─────────────

# [I1] scraper_ebay: usa OAuth2 directo con requests (NO requiere ebaysdk)
#      ebaysdk fue eliminado de pip install en daily_agent v6.2 + pipeline_roi v2.1
try:
    from .scraper_ebay import scrape_ebay
    _HAS_EBAY = True
except (ImportError, AttributeError) as e:
    scrape_ebay = None
    _HAS_EBAY   = False

# [I8] scraper_mercadolibre: movido de importlib a try/except
#      (archivo existe en repo — 0 resultados en log, posible cambio de API)
try:
    from .scraper_mercadolibre import scrape_mercadolibre
    _HAS_MERCADOLIBRE = True
except (ImportError, AttributeError) as e:
    scrape_mercadolibre = None
    _HAS_MERCADOLIBRE   = False

# [I8] scraper_newegg: movido de importlib a try/except
#      (archivo existe en repo — 0 resultados en log, posible cambio de HTML)
try:
    from .scraper_newegg import scrape_newegg
    _HAS_NEWEGG = True
except (ImportError, AttributeError) as e:
    scrape_newegg = None
    _HAS_NEWEGG   = False

# [I2] scraper_camel: 0 resultados en log, estado incierto
try:
    from .scraper_camel import scrape_camel
    _HAS_CAMEL = True
except (ImportError, AttributeError) as e:
    scrape_camel = None
    _HAS_CAMEL   = False

# [I3] scraper_pcpartpicker: 0 resultados en log
try:
    from .scraper_pcpartpicker import scrape_pcpartpicker
    _HAS_PCPARTPICKER = True
except (ImportError, AttributeError) as e:
    scrape_pcpartpicker = None
    _HAS_PCPARTPICKER   = False

# [I4] scraper_kaggle: usa 'import kaggle' internamente,
#      posible conflicto con kagglesdk en site-packages
try:
    from .scraper_kaggle import scrape_kaggle
    _HAS_KAGGLE = True
except (ImportError, AttributeError) as e:
    scrape_kaggle = None
    _HAS_KAGGLE   = False

# Scrapers activos confirmados en log
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

# ── [I6] Stubs para scrapers opcionales en None ────────────────────────────
# main.py DEBE verificar el flag _HAS_* antes de llamar a cualquier scraper
# opcional. Ejemplo correcto:
#
#   if _HAS_EBAY and scrape_ebay is not None:
#       results = scrape_ebay(...)
#   else:
#       logger.warning("scraper_ebay no disponible — omitiendo")

__all__ = [
    # Scrapers CORE — siempre disponibles
    "scrape_local",
    "scrape_dolar",
    "get_exchange_rate",
    # Scrapers OPCIONALES (pueden ser None si el import falló)
    "scrape_ebay",
    "scrape_mercadolibre",   # [I9]
    "scrape_newegg",         # [I9]
    "scrape_camel",
    "scrape_pcpartpicker",
    "scrape_kaggle",
    "scrape_importacion",
    "scrape_competencia",
    # Flags de disponibilidad — verificar ANTES de llamar al scraper
    "_HAS_EBAY",
    "_HAS_MERCADOLIBRE",     # [I9]
    "_HAS_NEWEGG",           # [I9]
    "_HAS_CAMEL",
    "_HAS_PCPARTPICKER",
    "_HAS_KAGGLE",
    "_HAS_IMPORTACION",
    "_HAS_COMPETENCIA",
]
