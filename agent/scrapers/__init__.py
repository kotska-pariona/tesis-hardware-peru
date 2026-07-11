"""
agent/scrapers/__init__.py  v3.0
Expone todos los scrapers como paquete importable desde agent/main.py

Scrapers activos (confirmado en log batch_20260710_221123):
  - scrape_local()          → Falabella, Hiraoka (PEN)
  - scrape_dolar()          → USD/PEN tipo de cambio (cascada 3 fuentes)
  - get_exchange_rate()     → Tipo de cambio actual (para roi_calculator.py)
  - scrape_importacion()    → Precios de importación (Amazon USA activo)
  - scrape_competencia()    → Análisis competencia local PE (Falabella activo)

Scrapers con try/except (opcionales — 0 resultados en log):
  - scrape_ebay()           → eBay Browse API USA (requiere EBAY_APP_ID)
  - scrape_camel()          → CamelCamelCamel RSS + historial ASIN
  - scrape_pcpartpicker()   → PCPartPicker precios multi-tienda USA
  - scrape_kaggle()         → Datasets Kaggle (bulk histórico)

Scrapers cargados via importlib en main.py (pueden no existir en el repo):
  - scrape_mercadolibre()   → MeLi PE API pública (HTTP 403 activo)
  - scrape_newegg()         → Newegg USA HTML scraping (archivo pendiente)

Patrón de resiliencia:
  - import directo  → scraper CORE, siempre debe existir y funcionar
  - try/except      → scraper OPCIONAL, puede fallar sin romper el paquete
  - importlib       → scraper EXPERIMENTAL, puede no existir en el repo
"""

# ── Scrapers CORE — siempre disponibles ────────────────────────────────────
# Si alguno falla aquí, el pipeline entero debe fallar (son dependencias duras)
from .scraper_local import scrape_local
from .scraper_dolar import scrape_dolar, get_exchange_rate

# ── Scrapers OPCIONALES — try/except para no romper el paquete ─────────────
# [I1] scraper_ebay: movido a try/except — requiere ebaysdk en pip
#      (ebaysdk agregado en daily_agent v6.0 + pipeline_roi v2.0)
try:
    from .scraper_ebay import scrape_ebay
    _HAS_EBAY = True
except (ImportError, AttributeError) as e:
    scrape_ebay = None
    _HAS_EBAY   = False

# [I2] scraper_camel: movido a try/except — 0 resultados en log, estado incierto
try:
    from .scraper_camel import scrape_camel
    _HAS_CAMEL = True
except (ImportError, AttributeError) as e:
    scrape_camel = None
    _HAS_CAMEL   = False

# [I3] scraper_pcpartpicker: movido a try/except — 0 resultados en log
try:
    from .scraper_pcpartpicker import scrape_pcpartpicker
    _HAS_PCPARTPICKER = True
except (ImportError, AttributeError) as e:
    scrape_pcpartpicker = None
    _HAS_PCPARTPICKER   = False

# [I4] scraper_kaggle: movido a try/except — usa 'import kaggle' internamente,
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

# ── Scrapers EXPERIMENTALES — cargados via importlib en main.py ────────────
# [I5] Razón real: son scrapers opcionales que pueden no existir en el repo,
#      no se importan aquí para que main.py pueda manejar su ausencia con
#      un mensaje de advertencia explícito (en lugar de ImportError aquí).
#
#   scraper_mercadolibre → MeLi PE (HTTP 403 activo, archivo existe)
#   scraper_newegg       → Newegg USA (archivo pendiente de crear)

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
    "scrape_camel",
    "scrape_pcpartpicker",
    "scrape_kaggle",
    "scrape_importacion",
    "scrape_competencia",
    # Flags de disponibilidad — verificar ANTES de llamar al scraper
    "_HAS_EBAY",
    "_HAS_CAMEL",
    "_HAS_PCPARTPICKER",
    "_HAS_KAGGLE",
    "_HAS_IMPORTACION",
    "_HAS_COMPETENCIA",
]
