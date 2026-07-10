"""
config.py  v2.1
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
  │   └── config.py          ← este archivo   [FIX-v2.1]
  └── data/
      ├── raw/               ← CSVs del pipeline (batch_*.csv, MASTER_*.csv)
      ├── processed/         ← CSVs procesados (features, oportunidades)
      ├── models/            ← modelos ML
      └── logs/              ← logs unificados

Fixes v2.0:
  - [FIX-1] DATA_RAW_DIR = DATA_DIR / 'raw' — alineado con main.py
  - [FIX-2] MASTER_CSV definido y apunta a data/raw/MASTER_hardware_peru.csv
  - [FIX-3] LOGS_DIR unificado a DATA_DIR / 'logs' — alineado con main.py
  - [FIX-4] config.py en configuracion/ — encontrado por roi_calculator.py via sys.path
  - [FIX-5] DOLAR_CSV apunta a data/raw/ — consistente con scrapers
  - [FIX-6] validate() con checks adicionales (FLETE_BASE_USD, LIMITE_COURIER_USD)
  - [FIX-7] DATA_PROCESSED_DIR para CSVs de análisis (oportunidades, features)

Fixes v2.1:
  - [FIX-8]  IndentationError corregido — try/except movido fuera de validate()
  - [FIX-9]  LOG_FILE unificado a 'agent.log' — alineado con main.py
  - [FIX-10] Docstring actualizado: ubicación real = configuracion/config.py
"""

import os
import warnings
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Directorios base ──────────────────────────────────────────────────────
# configuracion/config.py → ROOT = configuracion/../ = raíz del repo
CONFIG_DIR = Path(__file__).resolve().parent   # configuracion/
ROOT_DIR   = CONFIG_DIR.parent                 # raíz del repo

BASE_DIR   = Path(os.getenv("BASE_DIR", str(ROOT_DIR)))

# FIX-1/3/7: Estructura de directorios unificada
DATA_DIR           = Path(os.getenv("DATA_DIR",      str(BASE_DIR / "data")))
DATA_RAW_DIR       = Path(os.getenv("DATA_RAW_DIR",  str(DATA_DIR / "raw")))
DATA_PROCESSED_DIR = Path(os.getenv("DATA_PROC_DIR", str(DATA_DIR / "processed")))
MODELS_DIR         = Path(os.getenv("MODELS_DIR",    str(DATA_DIR / "models")))
LOGS_DIR           = Path(os.getenv("LOGS_DIR",      str(DATA_DIR / "logs")))

for _d in [DATA_DIR, DATA_RAW_DIR, DATA_PROCESSED_DIR, MODELS_DIR, LOGS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Archivos de datos ─────────────────────────────────────────────────────
MASTER_CSV          = DATA_RAW_DIR / "MASTER_hardware_peru.csv"

# Legacy — mantenidos para compatibilidad
MASTER_LOCAL_CSV    = DATA_RAW_DIR / "master_local.csv"
MASTER_IMPORT_CSV   = DATA_RAW_DIR / "master_importacion.csv"
MASTER_MERGED_CSV   = DATA_RAW_DIR / "master_merged.csv"

DOLAR_CSV           = DATA_RAW_DIR / "historial_dolar.csv"

FEATURES_CSV        = DATA_PROCESSED_DIR / "features_dataset.csv"
OPORTUNIDADES_CSV   = DATA_PROCESSED_DIR / "oportunidades_roi.csv"

# ── Logs ──────────────────────────────────────────────────────────────────
LOG_LEVEL           = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE            = LOGS_DIR / "agent.log"   # FIX-9: alineado con main.py

# ── Scraping — General ────────────────────────────────────────────────────
DELAY_REQ           = float(os.getenv("DELAY_REQ",          "2.5"))
DELAY_CAT           = float(os.getenv("DELAY_CAT",          "5.0"))
MAX_PAGES           = int(os.getenv("MAX_PAGES",             "5"))
MAX_PAGES_IMPORT    = int(os.getenv("MAX_PAGES_IMPORT",      "5"))
MAX_PAGES_COMP      = int(os.getenv("MAX_PAGES_COMP",        "5"))
MAX_RETRIES         = int(os.getenv("MAX_RETRIES",           "2"))

# ── Fuentes ───────────────────────────────────────────────────────────────
SOURCES_LOCAL       = ["falabella", "ripley", "hiraoka"]
SOURCES_IMPORT      = ["amazon", "aliexpress", "ebay"]
CATEGORIES          = ["CPU", "GPU", "RAM", "SSD", "MOTHERBOARD", "PSU", "COOLER", "CASE"]

# ── ROI — Costos de importación (SUNAT 2024) ──────────────────────────────
ARANCEL_AD_VALOREM  = float(os.getenv("ARANCEL_AD_VALOREM",  "0.00"))  # 0% electrónica
IGV                 = float(os.getenv("IGV",                 "0.18"))  # 18%
IPM                 = float(os.getenv("IPM",                 "0.02"))  # 2%
FLETE_BASE_USD      = float(os.getenv("FLETE_BASE_USD",      "25.0"))  # courier base USA→PE
FLETE_POR_KG_USD    = float(os.getenv("FLETE_POR_KG_USD",    "8.0"))   # por kg adicional
SEGURO_PCT          = float(os.getenv("SEGURO_PCT",          "0.005")) # 0.5% del FOB
GASTO_DESPACHO_USD  = float(os.getenv("GASTO_DESPACHO_USD",  "15.0"))  # despacho aduanero
MARGEN_GANANCIA_MIN = float(os.getenv("MARGEN_GANANCIA_MIN", "0.15"))  # 15% ROI mínimo
LIMITE_COURIER_USD  = float(os.getenv("LIMITE_COURIER_USD",  "200.0")) # DS 2024: exento < $200

# ── Tipo de cambio ────────────────────────────────────────────────────────
USD_PEN_DEFAULT     = float(os.getenv("USD_PEN_DEFAULT",     "3.75"))  # fallback
DOLAR_UPDATE_HOURS  = int(os.getenv("DOLAR_UPDATE_HOURS",    "6"))

# ── APIs externas ─────────────────────────────────────────────────────────
EBAY_APP_ID         = os.getenv("EBAY_APP_ID",         "")
EBAY_CLIENT_SECRET  = os.getenv("EBAY_CLIENT_SECRET",  "")
AMAZON_ACCESS_KEY   = os.getenv("AMAZON_ACCESS_KEY",   "")
AMAZON_SECRET_KEY   = os.getenv("AMAZON_SECRET_KEY",   "")
AMAZON_PARTNER_TAG  = os.getenv("AMAZON_PARTNER_TAG",  "")
KAGGLE_USERNAME     = os.getenv("KAGGLE_USERNAME",     "")
KAGGLE_KEY          = os.getenv("KAGGLE_KEY",          "")

# ── ML — Parámetros ───────────────────────────────────────────────────────
ML_TEST_SIZE        = float(os.getenv("ML_TEST_SIZE",        "0.2"))
ML_RANDOM_STATE     = int(os.getenv("ML_RANDOM_STATE",       "42"))
ML_MIN_RECORDS      = int(os.getenv("ML_MIN_RECORDS",        "500"))
LSTM_LOOKBACK_DAYS  = int(os.getenv("LSTM_LOOKBACK_DAYS",    "30"))
LSTM_FORECAST_DAYS  = int(os.getenv("LSTM_FORECAST_DAYS",    "7"))


# ── Validación robusta ────────────────────────────────────────────────────
def validate() -> bool:
    """Valida que los parámetros críticos del ROI sean coherentes."""
    issues = []
    if IGV <= 0:
        issues.append(f"IGV debe ser > 0 (actual: {IGV})")
    if IPM < 0:
        issues.append(f"IPM debe ser >= 0 (actual: {IPM})")
    if MARGEN_GANANCIA_MIN <= 0:
        issues.append(f"MARGEN_GANANCIA_MIN debe ser > 0 (actual: {MARGEN_GANANCIA_MIN})")
    if FLETE_BASE_USD <= 0:
        issues.append(f"FLETE_BASE_USD debe ser > 0 (actual: {FLETE_BASE_USD})")
    if LIMITE_COURIER_USD <= 0:
        issues.append(f"LIMITE_COURIER_USD debe ser > 0 (actual: {LIMITE_COURIER_USD})")
    if USD_PEN_DEFAULT <= 0:
        issues.append(f"USD_PEN_DEFAULT debe ser > 0 (actual: {USD_PEN_DEFAULT})")
    if issues:
        raise ValueError(f"config.py inválido: {'; '.join(issues)}")
    return True


# FIX-8: try/except FUERA de validate() y con indentación correcta
# Se ejecuta al importar el módulo — detecta .env mal configurado temprano
try:
    validate()
except ValueError as e:
    warnings.warn(str(e), stacklevel=2)


if __name__ == "__main__":
    validate()
    print("✅ config.py v2.1 OK")
    print(f"\n  Directorios:")
    print(f"    ROOT_DIR           : {ROOT_DIR}")
    print(f"    DATA_RAW_DIR       : {DATA_RAW_DIR}")
    print(f"    DATA_PROCESSED_DIR : {DATA_PROCESSED_DIR}")
    print(f"    MODELS_DIR         : {MODELS_DIR}")
    print(f"    LOGS_DIR           : {LOGS_DIR}")
    print(f"\n  Archivos clave:")
    print(f"    MASTER_CSV         : {MASTER_CSV}")
    print(f"    OPORTUNIDADES_CSV  : {OPORTUNIDADES_CSV}")
    print(f"    DOLAR_CSV          : {DOLAR_CSV}")
    print(f"    LOG_FILE           : {LOG_FILE}")
    print(f"\n  ROI (SUNAT 2024):")
    print(f"    IGV                : {IGV*100:.0f}%")
    print(f"    IPM                : {IPM*100:.0f}%")
    print(f"    Ad Valorem         : {ARANCEL_AD_VALOREM*100:.0f}%")
    print(f"    Flete base         : ${FLETE_BASE_USD}")
    print(f"    Límite courier     : ${LIMITE_COURIER_USD}")
    print(f"    Margen mínimo      : {MARGEN_GANANCIA_MIN*100:.0f}%")
    print(f"    USD/PEN default    : S/ {USD_PEN_DEFAULT}")
