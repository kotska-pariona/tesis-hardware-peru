"""
config.py
══════════
Fuente única de verdad para todas las constantes del proyecto.
Todos los demás módulos importan desde aquí.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Directorios ───────────────────────────────────────────────────────────────
BASE_DIR    = Path(os.getenv("BASE_DIR",    str(Path(__file__).parent)))
DATA_DIR    = Path(os.getenv("DATA_DIR",    str(BASE_DIR / "data")))
MODELS_DIR  = Path(os.getenv("MODELS_DIR",  str(BASE_DIR / "models")))
LOGS_DIR    = Path(os.getenv("LOGS_DIR",    str(BASE_DIR / "logs")))

for _d in [DATA_DIR, MODELS_DIR, LOGS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Archivos master ───────────────────────────────────────────────────────────
MASTER_LOCAL_CSV    = DATA_DIR / "master_local.csv"
MASTER_IMPORT_CSV   = DATA_DIR / "master_importacion.csv"
MASTER_MERGED_CSV   = DATA_DIR / "master_merged.csv"
FEATURES_CSV        = DATA_DIR / "features_dataset.csv"
DOLAR_CSV           = DATA_DIR / "historial_dolar.csv"
OPORTUNIDADES_CSV   = DATA_DIR / "oportunidades_roi.csv"

# ── Scraping — General ────────────────────────────────────────────────────────
DELAY_REQ   = float(os.getenv("DELAY_REQ",  "2.5"))   # segundos entre requests
DELAY_CAT   = float(os.getenv("DELAY_CAT",  "5.0"))   # segundos entre categorías
MAX_PAGES   = int(os.getenv("MAX_PAGES",    "5"))      # páginas por query (local)
MAX_PAGES_IMPORT = int(os.getenv("MAX_PAGES_IMPORT", "5"))  # páginas importación
MAX_RETRIES = int(os.getenv("MAX_RETRIES",  "2"))      # reintentos por query

# ── Scraping — Fuentes locales PE ─────────────────────────────────────────────
SOURCES_LOCAL    = ["falabella", "ripley", "hiraoka"]
SOURCES_IMPORT   = ["amazon", "aliexpress", "ebay"]

# ── Categorías ────────────────────────────────────────────────────────────────
CATEGORIES = ["CPU", "GPU", "RAM", "SSD", "MOTHERBOARD", "PSU", "COOLER", "CASE"]

# ── ROI — Costos de importación (Perú) ───────────────────────────────────────
# Fuente: SUNAT + tarifas courier 2024
ARANCEL_AD_VALOREM  = float(os.getenv("ARANCEL_AD_VALOREM",  "0.00"))  # 0% electrónica
IGV                 = float(os.getenv("IGV",                 "0.18"))  # 18%
IPM                 = float(os.getenv("IPM",                 "0.02"))  # 2% Impuesto Prom. Municipal
FLETE_BASE_USD      = float(os.getenv("FLETE_BASE_USD",      "25.0"))  # envío courier base
FLETE_POR_KG_USD    = float(os.getenv("FLETE_POR_KG_USD",    "8.0"))   # por kg adicional
SEGURO_PCT          = float(os.getenv("SEGURO_PCT",          "0.005")) # 0.5% del valor
GASTO_DESPACHO_USD  = float(os.getenv("GASTO_DESPACHO_USD",  "15.0"))  # gastos de despacho
MARGEN_GANANCIA_MIN = float(os.getenv("MARGEN_GANANCIA_MIN", "0.15"))  # 15% mínimo para recomendar
LIMITE_COURIER_USD  = float(os.getenv("LIMITE_COURIER_USD",  "200.0")) # límite sin declarar

# ── Tipo de cambio ────────────────────────────────────────────────────────────
USD_PEN_DEFAULT     = float(os.getenv("USD_PEN_DEFAULT", "3.75"))  # fallback si no hay API
DOLAR_UPDATE_HOURS  = int(os.getenv("DOLAR_UPDATE_HOURS", "6"))    # actualizar cada N horas

# ── APIs externas (opcionales) ────────────────────────────────────────────────
EBAY_APP_ID         = os.getenv("EBAY_APP_ID", "")
AMAZON_ACCESS_KEY   = os.getenv("AMAZON_ACCESS_KEY", "")
AMAZON_SECRET_KEY   = os.getenv("AMAZON_SECRET_KEY", "")
AMAZON_PARTNER_TAG  = os.getenv("AMAZON_PARTNER_TAG", "")

# ── ML — Parámetros ───────────────────────────────────────────────────────────
ML_TEST_SIZE        = float(os.getenv("ML_TEST_SIZE",   "0.2"))
ML_RANDOM_STATE     = int(os.getenv("ML_RANDOM_STATE",  "42"))
ML_MIN_RECORDS      = int(os.getenv("ML_MIN_RECORDS",   "500"))   # mínimo para entrenar
LSTM_LOOKBACK_DAYS  = int(os.getenv("LSTM_LOOKBACK_DAYS","30"))   # ventana histórica
LSTM_FORECAST_DAYS  = int(os.getenv("LSTM_FORECAST_DAYS","7"))    # días a predecir

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL   = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE    = LOGS_DIR / "pipeline.log"

# ── Validación al importar ────────────────────────────────────────────────────
def validate():
    issues = []
    if IGV <= 0:
        issues.append("IGV debe ser > 0")
    if MARGEN_GANANCIA_MIN <= 0:
        issues.append("MARGEN_GANANCIA_MIN debe ser > 0")
    if issues:
        raise ValueError(f"config.py inválido: {'; '.join(issues)}")
    return True

if __name__ == "__main__":
    validate()
    print("✅ config.py OK")
    print(f"  DATA_DIR    : {DATA_DIR}")
    print(f"  MODELS_DIR  : {MODELS_DIR}")
    print(f"  IGV         : {IGV*100:.0f}%")
    print(f"  Arancel     : {ARANCEL_AD_VALOREM*100:.0f}%")
    print(f"  Flete base  : ${FLETE_BASE_USD}")
    print(f"  USD/PEN def : {USD_PEN_DEFAULT}")
