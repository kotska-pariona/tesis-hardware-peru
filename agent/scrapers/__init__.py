"""
agent/scrapers/__init__.py  v3.2
Expone todos los scrapers como paquete importable desde agent/main.py

CAMBIOS v3.2 (sobre v3.1):
  [I10] Todos los bloques try/except ahora capturan el mensaje de error
        real en una variable _*_err (patrón ya usado por
        _load_optional_scraper() en main.py) y lo registran de
        inmediato con logging.warning() al momento de importar el
        paquete. Antes, la excepción `e` se capturaba pero nunca se
        usaba — un fallo real (no solo "archivo no encontrado", sino
        un ImportError interno del módulo, ej. dependencia faltante)
        quedaba completamente silenciado, sin ningún rastro en logs.
  [I11] except (ImportError, AttributeError) ampliado a except Exception
        en todos los scrapers OPCIONALES. Un error de inicialización
        distinto a ImportError/AttributeError (ej. el conflicto
        conocido entre 'kaggle' y 'kagglesdk' mencionado en [I4], que
        puede manifestarse como otro tipo de excepción durante el
        import) mataba el paquete ENTERO en vez de solo desactivar
        ese scraper — exactamente lo opuesto al propósito de este
        patrón de resiliencia. NO se aplica a los scrapers CORE
        (scrape_local, scrape_dolar, get_exchange_rate), que deben
        seguir fallando de forma ruidosa si no cargan.
  [I12] Docstring corregido: la sección "Scrapers activos" mezclaba
        scrapers CORE (import directo, get_exchange_rate) con
        scrapers OPCIONALES que resultan estar funcionando
        actualmente (scrape_ebay, scrape_importacion,
        scrape_competencia — los tres con try/except). Se separan
        ahora en 3 categorías reales: CORE / OPCIONAL-ACTIVO /
        OPCIONAL-INACTIVO, consistente con la sección "Patrón de
        resiliencia" que ya definía import directo=CORE,
        try/except=OPCIONAL.
  [I13] NOTA CRÍTICA agregada sobre duplicación con main.py: desde
        [I8], scrape_mercadolibre y scrape_newegg se exponen aquí con
        _HAS_MERCADOLIBRE/_HAS_NEWEGG — pero main.py (v5.9+) NO los
        importa desde este paquete; mantiene su propia carga
        duplicada vía _load_optional_scraper() con nombres distintos
        (_HAS_MELI, _HAS_NEWEGG), cargando scraper_mercadolibre.py y
        scraper_newegg.py DOS VECES por dos mecanismos distintos.
        Esto no se corrige en este archivo (requiere cambio en
        main.py) pero se documenta explícitamente para que ambos
        lados se mantengan sincronizados en el futuro.

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
  - import directo  → scraper CORE, siempre debe existir y funcionar.
                       Si falla, el paquete ENTERO debe fallar
                       (dependencia dura, sin try/except).
  - try/except      → scraper OPCIONAL, puede fallar sin romper el
                       paquete. INCLUYE scrape_ebay, scrape_importacion
                       y scrape_competencia — están "activos" en el
                       sentido de que hoy funcionan, pero siguen siendo
                       OPCIONALES a nivel de carga (ver [I12]).
  - importlib       → NO USADO en este archivo — todos los scrapers
                       conocidos usan try/except. ADVERTENCIA [I13]:
                       main.py SÍ usa importlib por su cuenta para
                       scrape_mercadolibre/scrape_newegg, de forma
                       duplicada e independiente a este archivo.
"""

import logging

_log = logging.getLogger(__name__)

# ── Scrapers CORE — siempre disponibles ────────────────────────────────
# Si alguno falla aquí, el pipeline entero debe fallar (dependencias duras,
# SIN try/except a propósito — ver [I11]).
from .scraper_local import scrape_local
from .scraper_dolar import scrape_dolar, get_exchange_rate

# ── Scrapers OPCIONALES — try/except para no romper el paquete ─────────
# [I10][I11] Todos capturan Exception amplio + guardan/loguean el motivo
# real del fallo en _*_err, en vez de silenciarlo.

# [I1] scraper_ebay: usa OAuth2 directo con requests (NO requiere ebaysdk)
#      ebaysdk fue eliminado de pip install en daily_agent v6.2 + pipeline_roi v2.1
try:
    from .scraper_ebay import scrape_ebay
    _HAS_EBAY = True
    _ebay_err = None
except Exception as e:                                    # [I11]
    scrape_ebay = None
    _HAS_EBAY   = False
    _ebay_err   = str(e)                                   # [I10]
    _log.warning(f"scraper_ebay no disponible: {_ebay_err}")

# [I8] scraper_mercadolibre: movido de importlib a try/except
#      (archivo existe en repo — 0 resultados en log, posible cambio de API)
# [I13] ADVERTENCIA: main.py NO usa esta variable — mantiene su propia
#      carga duplicada vía _load_optional_scraper(). Ver changelog v3.2.
try:
    from .scraper_mercadolibre import scrape_mercadolibre
    _HAS_MERCADOLIBRE = True
    _mercadolibre_err = None
except Exception as e:                                    # [I11]
    scrape_mercadolibre = None
    _HAS_MERCADOLIBRE   = False
    _mercadolibre_err   = str(e)                            # [I10]
    _log.warning(f"scraper_mercadolibre no disponible: {_mercadolibre_err}")

# [I8] scraper_newegg: movido de importlib a try/except
#      (archivo existe en repo — 0 resultados en log, posible cambio de HTML)
# [I13] ADVERTENCIA: main.py NO usa esta variable — mismo caso que arriba.
try:
    from .scraper_newegg import scrape_newegg
    _HAS_NEWEGG = True
    _newegg_err = None
except Exception as e:                                    # [I11]
    scrape_newegg = None
    _HAS_NEWEGG   = False
    _newegg_err   = str(e)                                  # [I10]
    _log.warning(f"scraper_newegg no disponible: {_newegg_err}")

# [I2] scraper_camel: 0 resultados en log, estado incierto
try:
    from .scraper_camel import scrape_camel
    _HAS_CAMEL = True
    _camel_err = None
except Exception as e:                                    # [I11]
    scrape_camel = None
    _HAS_CAMEL   = False
    _camel_err   = str(e)                                   # [I10]
    _log.warning(f"scraper_camel no disponible: {_camel_err}")

# [I3] scraper_pcpartpicker: 0 resultados en log
try:
    from .scraper_pcpartpicker import scrape_pcpartpicker
    _HAS_PCPARTPICKER = True
    _pcpartpicker_err = None
except Exception as e:                                    # [I11]
    scrape_pcpartpicker = None
    _HAS_PCPARTPICKER   = False
    _pcpartpicker_err   = str(e)                            # [I10]
    _log.warning(f"scraper_pcpartpicker no disponible: {_pcpartpicker_err}")

# [I4] scraper_kaggle: usa 'import kaggle' internamente,
#      posible conflicto con kagglesdk en site-packages — precisamente
#      el tipo de fallo que [I11] ahora captura de forma amplia en vez
#      de solo ImportError/AttributeError.
try:
    from .scraper_kaggle import scrape_kaggle
    _HAS_KAGGLE = True
    _kaggle_err = None
except Exception as e:                                    # [I11]
    scrape_kaggle = None
    _HAS_KAGGLE   = False
    _kaggle_err   = str(e)                                  # [I10]
    _log.warning(f"scraper_kaggle no disponible: {_kaggle_err}")

# Scrapers activos confirmados en log (OPCIONALES a nivel de carga — [I12])
try:
    from .scraper_importacion import scrape_importacion
    _HAS_IMPORTACION = True
    _importacion_err = None
except Exception as e:                                    # [I11]
    scrape_importacion = None
    _HAS_IMPORTACION   = False
    _importacion_err   = str(e)                             # [I10]
    _log.warning(f"scraper_importacion no disponible: {_importacion_err}")

try:
    from .scraper_competencia import scrape_competencia
    _HAS_COMPETENCIA = True
    _competencia_err = None
except Exception as e:                                    # [I11]
    scrape_competencia = None
    _HAS_COMPETENCIA   = False
    _competencia_err   = str(e)                             # [I10]
    _log.warning(f"scraper_competencia no disponible: {_competencia_err}")

# ── [I6] Stubs para scrapers opcionales en None ────────────────────────
# main.py DEBE verificar el flag _HAS_* antes de llamar a cualquier scraper
# opcional. Ejemplo correcto:
#
#   if _HAS_EBAY and scrape_ebay is not None:
#       results = scrape_ebay(...)
#   else:
#       logger.warning(f"scraper_ebay no disponible: {_ebay_err}")  # [I10]

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
    # [I10] Mensajes de error reales — None si el scraper cargó bien
    "_ebay_err",
    "_mercadolibre_err",
    "_newegg_err",
    "_camel_err",
    "_pcpartpicker_err",
    "_kaggle_err",
    "_importacion_err",
    "_competencia_err",
]
