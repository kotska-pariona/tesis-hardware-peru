"""
scraper_kaggle.py  v2.0
Descarga automática de datasets de hardware/electrónica desde Kaggle.

Requiere: KAGGLE_USERNAME + KAGGLE_KEY en secrets
Obtén tu API key en: https://www.kaggle.com/settings → API → Create New Token

Fixes v2.0:
  - [FIX-1] KAGGLE_DIR.mkdir() movido dentro de scrape_kaggle() — no en top-level
  - [FIX-2] Dataset IDs corregidos (3 de 6 eran 404)
  - [FIX-3] _clean_price() reemplazada por _parse_price() robusta
  - [FIX-4] df.get() corregido a verificación con 'in df.columns'
  - [FIX-5] filter_categories con re.escape()
  - [FIX-6] Caché de descarga — skip si existe y tiene <7 días
  - [FIX-7] import kaggle movido al top con try/except
  - [FIX-8] Laptop dataset: mapeo de Price_euros agregado
  - [FIX-9] max_rows configurable por dataset en TARGET_DATASETS
  - [FIX-10] source alias legible por dataset
  - [FIX-11] Nota de .gitignore para data/kaggle/
"""

import os
import re
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd

# FIX-7: import kaggle al top con manejo de ImportError
try:
    import kaggle as kaggle_lib
    KAGGLE_AVAILABLE = True
except ImportError:
    kaggle_lib       = None
    KAGGLE_AVAILABLE = False

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
KAGGLE_USERNAME = os.getenv("KAGGLE_USERNAME", "")
KAGGLE_KEY      = os.getenv("KAGGLE_KEY", "")

BASE_DIR     = Path(__file__).resolve().parent.parent.parent
DATA_RAW_DIR = BASE_DIR / "data" / "raw"
KAGGLE_DIR   = BASE_DIR / "data" / "kaggle"
# FIX-1: mkdir() removido del top-level — se llama dentro de scrape_kaggle()

CACHE_MAX_AGE_DAYS = 7   # FIX-6: re-descargar si el dataset tiene más de 7 días

# ──────────────────────────────────────────────
# FIX-2: Dataset IDs corregidos + FIX-9: max_rows + FIX-10: alias
# ──────────────────────────────────────────────
TARGET_DATASETS = {
    # ── Prioridad 1: datasets con precio USD directo ───────────────────
    "asaniczka/amazon-products-dataset-2023-1-4m-products": {
        "alias":       "amazon_2023",
        "description": "1.4M productos Amazon con precios (2023)",
        "priority":    1,
        "max_rows":    100_000,   # FIX-9: 100k de 1.4M = muestra representativa
        "columns_map": {
            "title":        "title",
            "price":        "price_usd",
            "categoryName": "category",
            "stars":        "rating",
            "reviews":      "reviews",
        },
        "filter_categories": [
            "Computers", "Electronics", "Laptops",
            "Monitors", "Computer Components",
        ],
        "price_currency": "USD",
    },
    "promptcloud/amazon-product-dataset-2020": {
        "alias":       "amazon_2020",
        "description": "Productos Amazon con precios y ratings (2020)",
        "priority":    1,
        "max_rows":    50_000,
        "columns_map": {
            "product_name":  "title",
            "selling_price": "price_usd",
            "category":      "category",
        },
        "filter_categories": [],
        "price_currency": "USD",
    },
    # FIX-2: Corregido de 'the-ultimate-laptop-price-predictor' → 'laptop-prices-dataset'
    "thedevastator/laptop-prices-dataset": {
        "alias":       "laptops_specs",
        "description": "Dataset de laptops con specs y precios en euros",
        "priority":    1,
        "max_rows":    50_000,
        "columns_map": {
            "Company":      "brand",
            "Product":      "title",
            "Ram":          "ram",
            "Memory":       "storage",
            "Price_euros":  "price_usd",   # FIX-8: mapeo de precio agregado
            "Price":        "price_usd",   # Alias alternativo
        },
        "filter_categories": [],
        "price_currency": "EUR",           # FIX-11: nota de moneda
    },
    "muhammetvarl/gpu-prices": {
        "alias":       "gpu_prices",
        "description": "Historial de precios de GPUs",
        "priority":    1,
        "max_rows":    50_000,
        "columns_map": {
            "name":  "title",
            "price": "price_usd",
            "date":  "price_date",
        },
        "filter_categories": [],
        "price_currency": "USD",
    },
    # FIX-2: Reemplazado 'iliassekkaf/pc-hardware-prices' (404) por dataset válido
    "brendan45774/computer-parts": {
        "alias":       "pc_parts",
        "description": "Componentes PC con precios — Amazon USA",
        "priority":    1,
        "max_rows":    50_000,
        "columns_map": {
            "name":     "title",
            "price":    "price_usd",
            "category": "category",
        },
        "filter_categories": [],
        "price_currency": "USD",
    },
    # FIX-2: Corregido case 'PromptCloudHQ' → 'promptcloudhq' (minúsculas)
    "promptcloudhq/flipkart-products": {
        "alias":       "flipkart",
        "description": "Productos Flipkart — referencia precios Asia (rupias)",
        "priority":    2,
        "max_rows":    30_000,
        "columns_map": {
            "product_name":          "title",
            "discounted_price":      "price_usd",
            "product_category_tree": "category",
        },
        "filter_categories": [],
        "price_currency": "INR",   # FIX-11: rupias — NO son USD
    },
}


# ──────────────────────────────────────────────
# FIX-3: Parser de precios robusto
# (reutiliza lógica de scraper_dolar.py)
# ──────────────────────────────────────────────

def _parse_price_str(text: str) -> Optional[float]:
    """
    Convierte texto de precio a float manejando múltiples formatos:
      '$1,299.99' → 1299.99
      '1.299,99'  → 1299.99
      '₹45,000'   → 45000.0  (se marcará con currency=INR)
      '1,4'       → 1.4      (europeo decimal)
      '45000'     → 45000.0
    """
    if not text or str(text).strip() in ("", "nan", "None", "N/A"):
        return None
    clean = re.sub(r"[^\d,.]", "", str(text).strip())
    if not clean:
        return None
    try:
        if "," in clean and "." in clean:
            last_comma = clean.rfind(",")
            last_dot   = clean.rfind(".")
            if last_comma > last_dot:
                clean = clean.replace(".", "").replace(",", ".")
            else:
                clean = clean.replace(",", "")
        elif "," in clean:
            parts = clean.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                clean = clean.replace(",", ".")   # decimal: 1,4 → 1.4
            else:
                clean = clean.replace(",", "")    # miles: 1,000 → 1000
        val = float(clean)
        return val if val > 0 else None
    except ValueError:
        return None


def _clean_price_series(series: pd.Series) -> pd.Series:
    """Aplica _parse_price_str a toda una columna."""
    return series.map(_parse_price_str)


# ──────────────────────────────────────────────
# SETUP CREDENCIALES
# ──────────────────────────────────────────────

def _setup_kaggle_credentials() -> bool:
    if not KAGGLE_USERNAME or not KAGGLE_KEY:
        logger.error(
            "❌ KAGGLE_USERNAME o KAGGLE_KEY no configurados.\n"
            "   Obtén tu API key en: https://www.kaggle.com/settings → API"
        )
        return False

    kaggle_dir  = Path.home() / ".kaggle"
    kaggle_dir.mkdir(exist_ok=True)
    kaggle_json = kaggle_dir / "kaggle.json"

    with open(kaggle_json, "w") as f:
        json.dump({"username": KAGGLE_USERNAME, "key": KAGGLE_KEY}, f)
    kaggle_json.chmod(0o600)

    logger.info("✅ Credenciales Kaggle configuradas")
    return True


# ──────────────────────────────────────────────
# FIX-6: Verificación de caché de descarga
# ──────────────────────────────────────────────

def _is_cached(dest: Path) -> bool:
    """
    Retorna True si el dataset ya fue descargado y tiene menos de CACHE_MAX_AGE_DAYS días.
    """
    csv_files = list(dest.glob("**/*.csv"))
    if not csv_files:
        return False
    # Verificar la fecha de modificación del CSV más reciente
    newest_mtime = max(f.stat().st_mtime for f in csv_files)
    age_days     = (datetime.now().timestamp() - newest_mtime) / 86400
    if age_days < CACHE_MAX_AGE_DAYS:
        logger.info(f"  📦 Cache hit: {dest.name} ({age_days:.1f} días de antigüedad)")
        return True
    return False


# ──────────────────────────────────────────────
# DESCARGA
# ──────────────────────────────────────────────

def _download_dataset(dataset_id: str) -> Optional[Path]:
    # FIX-7: usar kaggle_lib importado al top
    if not KAGGLE_AVAILABLE or kaggle_lib is None:
        logger.error("❌ kaggle no instalado. Ejecuta: pip install kaggle")
        return None

    dest = KAGGLE_DIR / dataset_id.replace("/", "_")
    dest.mkdir(parents=True, exist_ok=True)   # FIX-1: mkdir aquí, no en top-level

    # FIX-6: Skip si ya existe y es reciente
    if _is_cached(dest):
        return dest

    try:
        logger.info(f"  📥 Descargando: {dataset_id}")
        kaggle_lib.api.dataset_download_files(
            dataset_id, path=str(dest), unzip=True, quiet=False
        )
        logger.info(f"  ✅ Descargado en: {dest}")
        return dest
    except Exception as e:
        logger.warning(f"  ⚠️ Error descargando {dataset_id}: {e}")
        # Si hay archivos parciales del caché anterior, usarlos
        if list(dest.glob("**/*.csv")):
            logger.info(f"  ♻️ Usando datos anteriores de {dest.name}")
            return dest
        return None


# ──────────────────────────────────────────────
# NORMALIZACIÓN
# ──────────────────────────────────────────────

def _normalize_dataset(
    dataset_dir: Path,
    config: dict,
    dataset_id: str,
    batch_id: str,
) -> list:
    records      = []
    now_iso      = datetime.now(timezone.utc).isoformat()
    columns_map  = config.get("columns_map", {})
    filter_cats  = config.get("filter_categories", [])
    alias        = config.get("alias", dataset_id.split("/")[1])   # FIX-10
    max_rows     = config.get("max_rows", 50_000)                   # FIX-9
    price_currency = config.get("price_currency", "USD")            # FIX-11

    csv_files = list(dataset_dir.glob("**/*.csv"))
    if not csv_files:
        logger.warning(f"  ⚠️ Sin CSVs en {dataset_dir}")
        return records

    for csv_file in csv_files:
        try:
            logger.info(f"  📄 Procesando: {csv_file.name}")
            df = pd.read_csv(
                csv_file,
                low_memory=False,
                on_bad_lines="skip",
                encoding="utf-8",
                encoding_errors="replace",
            )
            logger.info(f"     Filas: {len(df):,} | Cols: {list(df.columns[:6])}")

            # Renombrar columnas (tomar el primero que matchee)
            rename_map = {}
            for orig, dest_col in columns_map.items():
                if orig in df.columns and dest_col not in rename_map.values():
                    rename_map[orig] = dest_col
            if rename_map:
                df = df.rename(columns=rename_map)

            # FIX-5: Filtrar por categoría con re.escape()
            if filter_cats and "category" in df.columns:
                pattern = "|".join(re.escape(c) for c in filter_cats)
                mask    = df["category"].astype(str).str.contains(
                    pattern, case=False, na=False
                )
                df = df[mask].copy()
                logger.info(f"     Filtrado: {len(df):,} filas")

            # Detectar columna de precio si no fue mapeada
            if "price_usd" not in df.columns:
                price_cols = [c for c in df.columns if "price" in c.lower()]
                if price_cols:
                    df = df.rename(columns={price_cols[0]: "price_usd"})

            # FIX-3: Limpiar precio con parser robusto
            if "price_usd" in df.columns:
                df["price_usd"] = _clean_price_series(df["price_usd"])
                df = df[df["price_usd"].notna() & (df["price_usd"] > 0)]

            # Asegurar columna title
            if "title" not in df.columns:
                title_cols = [
                    c for c in df.columns
                    if "name" in c.lower() or "title" in c.lower()
                ]
                if title_cols:
                    df = df.rename(columns={title_cols[0]: "title"})

            # FIX-4: df.get() corregido — DataFrame no tiene .get()
            if "price_date" not in df.columns:
                df["price_date"] = now_iso[:10]

            # Metadata
            df["batch_id"]        = batch_id
            df["timestamp"]       = now_iso
            df["source"]          = f"kaggle_{alias}"   # FIX-10: alias legible
            df["price_currency"]  = price_currency       # FIX-11: moneda explícita

            # FIX-9: Límite configurable por dataset
            subset = df.head(max_rows)
            batch  = subset.to_dict(orient="records")
            records.extend(batch)
            logger.info(f"     ✅ {len(batch):,} registros normalizados (currency={price_currency})")

        except Exception as e:
            logger.warning(f"  ⚠️ Error procesando {csv_file.name}: {e}")
            continue

    return records


# ──────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ──────────────────────────────────────────────

def scrape_kaggle(batch_id: str) -> list:
    """
    Descarga y normaliza datasets de Kaggle.
    Retorna lista de registros normalizados.
    Si no hay credenciales, retorna [] sin fallar.

    NOTA: data/kaggle/ debe estar en .gitignore — los archivos son >100MB.
    """
    # FIX-1: mkdir() aquí, no en top-level
    KAGGLE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)

    if not _setup_kaggle_credentials():
        logger.warning("[Kaggle] Sin credenciales — saltando")
        return []

    if not KAGGLE_AVAILABLE:
        logger.error("[Kaggle] Librería 'kaggle' no instalada — pip install kaggle")
        return []

    all_records = []

    sorted_datasets = sorted(
        TARGET_DATASETS.items(),
        key=lambda x: x[1].get("priority", 99)
    )

    for dataset_id, config in sorted_datasets:
        alias = config.get("alias", dataset_id.split("/")[1])
        logger.info(f"\n[Kaggle] Dataset: {dataset_id} (alias={alias})")
        logger.info(f"  {config['description']}")

        dataset_dir = _download_dataset(dataset_id)
        if dataset_dir is None:
            logger.warning(f"  ⏭️ Saltando {dataset_id} — descarga fallida")
            continue

        records = _normalize_dataset(dataset_dir, config, dataset_id, batch_id)
        all_records.extend(records)
        logger.info(f"  📊 Acumulado: {len(all_records):,} registros")

    logger.info(f"\n[Kaggle] TOTAL: {len(all_records):,} registros")
    return all_records


# ──────────────────────────────────────────────
# STANDALONE
# ──────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    batch   = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results = scrape_kaggle(batch)
    print(f"\nTotal: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
