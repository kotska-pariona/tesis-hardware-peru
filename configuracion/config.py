"""
config.py  v2.4
══════════════════
Fuente única de verdad para todas las constantes del proyecto.
Todos los demás módulos importan desde aquí.

Estructura de directorios unificada:
  ROOT/
  ├── agent/
  │   ├── main.py
  │   └── scrapers/
  ├── analisis/
  │   └── roi_calculator.py
  ├── configuracion/
  │   └── config.py          ← este archivo
  └── data/
      ├── raw/               ← CSVs del pipeline (batch_*.csv, MASTER_*.csv)
      ├── processed/         ← CSVs procesados (features, oportunidades)
      ├── models/            ← modelos ML
      └── logs/              ← logs unificados

Fixes v2.4 (sobre v2.3):
  [CFG1] SOURCES_LOCAL: +mercadolibre_pe ya estaba en [C4] pero faltaban
         los aliases normalizados 'falabella_pe' y 'hiraoka_pe' que emiten
         scraper_local v3.6 y scraper_competencia v4.1 — roi_calculator
         los clasificaba como 'other' en lugar de 'local_pe'
  [CFG2] SOURCES_IMPORT: +aliases Kaggle v3.1 (kaggle_amazon_2023,
         kaggle_amazon_2020, kaggle_amazon_pc_parts, kaggle_flipkart,
         kaggle_laptops_specs, kaggle_gpu_prices) — consistente con [ROI6]
         de roi_calculator v3.1
  [CFG3] DE_MINIMIS_USD: 100.0 → 200.0 — SUNAT Resolución 000026-2024
         establece $200 CIF, no $100; [C12] en v2.3 era incorrecto.
         roi_calculator v3.1 usa _DE_MINIMIS_USD=200 (correcto); config.py
         debe ser consistente con él
  [CFG4] validate(): FLETE_POR_KG_USD check corregido — en v2.3 el check
         era FLETE_POR_KG_USD > FLETE_BASE_USD (8 > 35 = False, nunca dispara);
         el check correcto es FLETE_POR_KG_USD <= 0
  [CFG5] VERSION = "2.4"
"""

import os
import sys
import warnings
from pathlib import Path
from dotenv import load_dotenv

VERSION = "2.4"   # [CFG5]

# ── Paths ──────────────────────────────────────────────────────────────
CONFIG_DIR = Path(__file__).resolve().parent   # configuracion/
ROOT_DIR   = CONFIG_DIR.parent                 # raíz del repo

# [C3] Path explícito — independiente del CWD
load_dotenv(ROOT_DIR / ".env")

BASE_DIR = Path(os.getenv("BASE_DIR", str(ROOT_DIR)))


# ── [C8] Helpers seguros para variables de entorno numéricas ───────────
def _env_float(key: str, default: float) -> float:
    """Lee una variable de entorno como float. Si está vacía o es inválida, usa default."""
    val = os.getenv(key, "").strip()
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        warnings.warn(
            f"config.py: {key}='{val}' no es un float válido "
            f"— usando default {default}",
            stacklevel=3,
        )
        return default

def _env_int(key: str, default: int) -> int:
    """Lee una variable de entorno como int. Si está vacía o es inválida, usa default."""
    val = os.getenv(key, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        warnings.warn(
            f"config.py: {key}='{val}' no es un int válido "
            f"— usando default {default}",
            stacklevel=3,
        )
        return default


# ── Directorios base ───────────────────────────────────────────────────
DATA_DIR           = Path(os.getenv("DATA_DIR",      str(BASE_DIR / "data")))
DATA_RAW_DIR       = Path(os.getenv("DATA_RAW_DIR",  str(DATA_DIR / "raw")))
DATA_PROCESSED_DIR = Path(os.getenv("DATA_PROC_DIR", str(DATA_DIR / "processed")))
MODELS_DIR         = Path(os.getenv("MODELS_DIR",    str(DATA_DIR / "models")))
LOGS_DIR           = Path(os.getenv("LOGS_DIR",      str(DATA_DIR / "logs")))

# [C7] mkdir con try/except — no crashea en entornos read-only o en tests
for _d in [DATA_DIR, DATA_RAW_DIR, DATA_PROCESSED_DIR, MODELS_DIR, LOGS_DIR]:
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except PermissionError as _e:
        warnings.warn(
            f"config.py: no se pudo crear directorio {_d}: {_e}",
            stacklevel=2,
        )


# ── Archivos de datos ──────────────────────────────────────────────────
MASTER_CSV        = DATA_RAW_DIR / "MASTER_hardware_peru.csv"
MASTER_LOCAL_CSV  = DATA_RAW_DIR / "master_local.csv"        # legacy
MASTER_IMPORT_CSV = DATA_RAW_DIR / "master_importacion.csv"  # legacy
MASTER_MERGED_CSV = DATA_RAW_DIR / "master_merged.csv"       # legacy
DOLAR_CSV         = DATA_RAW_DIR / "historial_dolar.csv"
FEATURES_CSV      = DATA_PROCESSED_DIR / "features_dataset.csv"
OPORTUNIDADES_CSV = DATA_PROCESSED_DIR / "oportunidades_roi.csv"

# ── Logs ───────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE  = LOGS_DIR / "agent.log"

# ── Scraping — General ─────────────────────────────────────────────────
DELAY_REQ        = _env_float("DELAY_REQ",       2.5)
DELAY_CAT        = _env_float("DELAY_CAT",       5.0)
# [C5] MAX_PAGES: legacy — scrapers activos usan sus propios límites
MAX_PAGES        = _env_int("MAX_PAGES",          5)
MAX_PAGES_IMPORT = _env_int("MAX_PAGES_IMPORT",   5)
MAX_PAGES_COMP   = _env_int("MAX_PAGES_COMP",     5)
MAX_RETRIES      = _env_int("MAX_RETRIES",        2)

# [C4] + [C9] + [CFG1] SOURCES_LOCAL
# Incluye aliases _pe que emiten scraper_local v3.6 y scraper_competencia v4.1
# Sin ellos roi_calculator los clasificaba como 'other' en lugar de 'local_pe'
SOURCES_LOCAL = [
    # scraper_local v3.6
    "falabella_pe",              # [CFG1] alias real emitido por scraper
    "hiraoka_pe",                # [CFG1] alias real emitido por scraper
    "falabella", "hiraoka",      # aliases legacy
    # scraper_competencia v4.1 [C9]
    "coolbox", "compumundo",
    # scraper_mercadolibre v2.1 [C4]
    "mercadolibre_pe",
    # "ripley_pe" — deshabilitado (403 Cloudflare)
]

# [C4] + [C10] + [CFG2] SOURCES_IMPORT
# Incluye aliases Kaggle v3.1 — consistente con [ROI6] de roi_calculator v3.1
SOURCES_IMPORT = [
    "amazon", "aliexpress",
    "ebay_usa",                      # [C10]
    "newegg_usa",                    # [C4]
    "pcpartpicker_current",          # [C4]
    "pcpartpicker_history",          # [C4]
    # [CFG2] Kaggle v3.1 aliases
    "kaggle_amazon_2023",
    "kaggle_amazon_2020",
    "kaggle_amazon_pc_parts",
    "kaggle_flipkart",
    "kaggle_laptops_specs",
    "kaggle_gpu_prices",
]

# [C6] CATEGORIES: fuente única de verdad — alineada con CATEGORY_MAP
CATEGORIES = [
    # Hardware core
    "CPU", "GPU", "RAM", "SSD", "MOTHERBOARD", "PSU", "COOLER", "CASE",
    # Periféricos y dispositivos
    "LAPTOP", "MONITOR", "KEYBOARD", "MOUSE", "AUDIO",
    # Electrónica general
    "TABLET", "PHONE", "TV", "CAMERA", "GAMING",
    # "PRINTER" removido — ningún scraper activo la cubre [M12]
]

# ── ROI — Costos de importación (SUNAT 2024-2026) ──────────────────────
ARANCEL_AD_VALOREM  = _env_float("ARANCEL_AD_VALOREM",  0.00)   # 0% electrónica
IGV                 = _env_float("IGV",                  0.18)   # 18%
IPM                 = _env_float("IPM",                  0.02)   # 2%
FLETE_BASE_USD      = _env_float("FLETE_BASE_USD",      35.0)    # [C11] courier 2026
FLETE_POR_KG_USD    = _env_float("FLETE_POR_KG_USD",    8.0)     # por kg adicional
SEGURO_PCT          = _env_float("SEGURO_PCT",           0.005)  # 0.5% del FOB
GASTO_DESPACHO_USD  = _env_float("GASTO_DESPACHO_USD",  15.0)   # despacho aduanero
MARGEN_GANANCIA_MIN = _env_float("MARGEN_GANANCIA_MIN",  0.15)  # 15% ROI mínimo

# [C1] + [CFG3] Umbrales SUNAT — SUNAT Resolución 000026-2024
# [CFG3] DE_MINIMIS_USD corregido a 200.0 — v2.3 tenía 100.0 (incorrecto)
#        roi_calculator v3.1 usa _DE_MINIMIS_USD=200 (correcto); config.py
#        debe ser consistente con él
DE_MINIMIS_USD          = _env_float("DE_MINIMIS_USD",          200.0)  # [CFG3]
LIMITE_SIMPLIFICADO_USD = _env_float("LIMITE_SIMPLIFICADO_USD", 2000.0)
LIMITE_COURIER_USD      = DE_MINIMIS_USD   # alias legacy — compatibilidad v2.3

# ── Tipo de cambio ─────────────────────────────────────────────────────
USD_PEN_DEFAULT    = _env_float("USD_PEN_DEFAULT",    3.75)
DOLAR_UPDATE_HOURS = _env_int("DOLAR_UPDATE_HOURS",   6)

# ── APIs externas ──────────────────────────────────────────────────────
EBAY_APP_ID        = os.getenv("EBAY_APP_ID",        "")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET", "")
AMAZON_ACCESS_KEY  = os.getenv("AMAZON_ACCESS_KEY",  "")
AMAZON_SECRET_KEY  = os.getenv("AMAZON_SECRET_KEY",  "")
AMAZON_PARTNER_TAG = os.getenv("AMAZON_PARTNER_TAG", "")
KAGGLE_USERNAME    = os.getenv("KAGGLE_USERNAME",     "")
KAGGLE_KEY         = os.getenv("KAGGLE_KEY",          "")

# ── ML — Parámetros ────────────────────────────────────────────────────
ML_TEST_SIZE       = _env_float("ML_TEST_SIZE",       0.2)
ML_RANDOM_STATE    = _env_int("ML_RANDOM_STATE",      42)
ML_MIN_RECORDS     = _env_int("ML_MIN_RECORDS",       100)   # [C15]
LSTM_LOOKBACK_DAYS = _env_int("LSTM_LOOKBACK_DAYS",   60)    # [C14]
LSTM_FORECAST_DAYS = _env_int("LSTM_FORECAST_DAYS",   7)


# ── Validación robusta ─────────────────────────────────────────────────
def validate() -> bool:
    """Valida que los parámetros críticos sean coherentes."""
    issues = []

    # ROI — obligatorios positivos
    if IGV <= 0:
        issues.append(f"IGV debe ser > 0 (actual: {IGV})")
    if IPM < 0:
        issues.append(f"IPM debe ser >= 0 (actual: {IPM})")
    if MARGEN_GANANCIA_MIN <= 0:
        issues.append(
            f"MARGEN_GANANCIA_MIN debe ser > 0 "
            f"(actual: {MARGEN_GANANCIA_MIN})"
        )
    if FLETE_BASE_USD <= 0:
        issues.append(
            f"FLETE_BASE_USD debe ser > 0 (actual: {FLETE_BASE_USD})"
        )
    if USD_PEN_DEFAULT <= 0:
        issues.append(
            f"USD_PEN_DEFAULT debe ser > 0 (actual: {USD_PEN_DEFAULT})"
        )

    # [C2] Checks adicionales
    if ARANCEL_AD_VALOREM < 0:
        issues.append(
            f"ARANCEL_AD_VALOREM debe ser >= 0 "
            f"(actual: {ARANCEL_AD_VALOREM})"
        )
    if SEGURO_PCT < 0:
        issues.append(
            f"SEGURO_PCT debe ser >= 0 (actual: {SEGURO_PCT})"
        )
    # [CFG4] Check corregido: FLETE_POR_KG_USD debe ser > 0
    #        En v2.3 el check era FLETE_POR_KG_USD > FLETE_BASE_USD
    #        (8 > 35 = False — nunca disparaba)
    if FLETE_POR_KG_USD <= 0:
        issues.append(
            f"FLETE_POR_KG_USD debe ser > 0 "
            f"(actual: {FLETE_POR_KG_USD})"
        )
    if GASTO_DESPACHO_USD < 0:
        issues.append(
            f"GASTO_DESPACHO_USD debe ser >= 0 "
            f"(actual: {GASTO_DESPACHO_USD})"
        )
    if not (0 < ML_TEST_SIZE < 1):
        issues.append(
            f"ML_TEST_SIZE debe estar en (0, 1) "
            f"(actual: {ML_TEST_SIZE})"
        )

    # [C1] + [CFG3] Coherencia umbrales SUNAT
    if DE_MINIMIS_USD <= 0:
        issues.append(
            f"DE_MINIMIS_USD debe ser > 0 (actual: {DE_MINIMIS_USD})"
        )
    if LIMITE_SIMPLIFICADO_USD <= DE_MINIMIS_USD:
        issues.append(
            f"LIMITE_SIMPLIFICADO_USD ({LIMITE_SIMPLIFICADO_USD}) debe "
            f"ser > DE_MINIMIS_USD ({DE_MINIMIS_USD})"
        )

    if issues:
        raise ValueError(f"config.py inválido: {'; '.join(issues)}")
    return True


# [C16] validate() al importar — fatal en CI/CD, warning en local
try:
    validate()
except ValueError as e:
    if os.getenv("GITHUB_ACTIONS") or os.getenv("CI"):
        print(f"FATAL config.py v{VERSION}: {e}", file=sys.stderr)
        sys.exit(1)
    else:
        warnings.warn(str(e), stacklevel=2)


if __name__ == "__main__":
    validate()
    print(f"✅ config.py v{VERSION} OK")
    print(f"\n  Directorios:")
    print(f"    ROOT_DIR               : {ROOT_DIR}")
    print(f"    DATA_RAW_DIR           : {DATA_RAW_DIR}")
    print(f"    DATA_PROCESSED_DIR     : {DATA_PROCESSED_DIR}")
    print(f"    MODELS_DIR             : {MODELS_DIR}")
    print(f"    LOGS_DIR               : {LOGS_DIR}")
    print(f"\n  Archivos clave:")
    print(f"    MASTER_CSV             : {MASTER_CSV}")
    print(f"    OPORTUNIDADES_CSV      : {OPORTUNIDADES_CSV}")
    print(f"    DOLAR_CSV              : {DOLAR_CSV}")
    print(f"    LOG_FILE               : {LOG_FILE}")
    print(f"\n  ROI (SUNAT 2024-2026):")
    print(f"    IGV                    : {IGV*100:.0f}%")
    print(f"    IPM                    : {IPM*100:.0f}%")
    print(f"    Ad Valorem             : {ARANCEL_AD_VALOREM*100:.0f}%")
    print(f"    Flete base             : ${FLETE_BASE_USD}  ← actualizado 2026")
    print(f"    Flete por kg           : ${FLETE_POR_KG_USD}/kg")
    print(
        f"    De minimis             : ${DE_MINIMIS_USD}  "
        f"(SUNAT Res. 000026-2024, sin impuestos)"
    )
    print(
        f"    Límite simplificado    : ${LIMITE_SIMPLIFICADO_USD}  "
        f"(IGV+IPM, sin Ad Valorem)"
    )
    print(f"    Margen mínimo          : {MARGEN_GANANCIA_MIN*100:.0f}%")
    print(f"    USD/PEN default        : S/ {USD_PEN_DEFAULT}")
    print(f"    Dolar update cada      : {DOLAR_UPDATE_HOURS}h")
    print(f"\n  Fuentes activas:")
    print(f"    Local PE               : {SOURCES_LOCAL}")
    print(f"    Importación            : {SOURCES_IMPORT}")
    print(f"\n  ML:")
    print(f"    Test size              : {ML_TEST_SIZE}")
    print(f"    Min records            : {ML_MIN_RECORDS}")
    print(f"    LSTM lookback          : {LSTM_LOOKBACK_DAYS} días")
    print(f"    LSTM forecast          : {LSTM_FORECAST_DAYS} días")
    print(f"\n  Categorías ({len(CATEGORIES)}): {CATEGORIES}")
