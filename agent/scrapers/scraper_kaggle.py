"""
scraper_kaggle.py
Descarga automática de datasets de hardware/electrónica desde Kaggle.

Requiere: KAGGLE_USERNAME + KAGGLE_KEY en secrets (gratuito en kaggle.com/settings)

Datasets objetivo:
  - Historial de precios de hardware PC
  - Precios de electrónica Amazon
  - Datasets de componentes de PC
"""

import os
import json
import shutil
import logging
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
KAGGLE_USERNAME = os.getenv("KAGGLE_USERNAME", "")
KAGGLE_KEY      = os.getenv("KAGGLE_KEY", "")

# Directorio base del proyecto (relativo a este archivo)
BASE_DIR      = Path(__file__).resolve().parent.parent.parent
DATA_RAW_DIR  = BASE_DIR / "data" / "raw"
KAGGLE_DIR    = BASE_DIR / "data" / "kaggle"
KAGGLE_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────
# DATASETS OBJETIVO
# Formato: { "dataset_id": { "description", "files", "columns_map" } }
# ──────────────────────────────────────────────
TARGET_DATASETS = {
    # ── Hardware / PC Components ──────────────────────────────────────────
    "iliassekkaf/pc-hardware-prices": {
        "description": "Precios históricos de componentes PC (CPU, GPU, RAM, SSD)",
        "priority": 1,
        "expected_files": ["pc_hardware_prices.csv"],
        "columns_map": {
            "name":       "title",
            "price":      "price_usd",
            "date":       "price_date",
            "category":   "category",
        },
    },
    "promptcloud/amazon-product-dataset-2020": {
        "description": "Dataset de productos Amazon con precios y ratings",
        "priority": 1,
        "expected_files": ["amazon_products.csv"],
        "columns_map": {
            "product_name":  "title",
            "selling_price": "price_usd",
            "category":      "category",
        },
    },
    "asaniczka/amazon-products-dataset-2023-1-4m-products": {
        "description": "1.4M productos Amazon con precios actuales (2023)",
        "priority": 1,
        "expected_files": ["amazon_products_2023.csv"],
        "columns_map": {
            "title":         "title",
            "price":         "price_usd",
            "categoryName":  "category",
            "stars":         "rating",
            "reviews":       "reviews",
            "isBestSeller":  "is_bestseller",
        },
        "filter_categories": [
            "Computers & Accessories",
            "Electronics",
            "Computer Components",
            "Laptops",
            "Monitors",
        ],
    },
    "PromptCloudHQ/flipkart-products": {
        "description": "Productos Flipkart (India) — referencia de precios Asia",
        "priority": 2,
        "expected_files": ["flipkart_com-ecommerce_sample.csv"],
        "columns_map": {
            "product_name":   "title",
            "retail_price":   "price_original",
            "discounted_price": "price_usd",
            "product_category_tree": "category",
        },
    },
    "thedevastator/the-ultimate-laptop-price-predictor": {
        "description": "Dataset de laptops con specs y precios",
        "priority": 1,
        "expected_files": ["laptop_price.csv", "laptops.csv"],
        "columns_map": {
            "Company":    "brand",
            "Product":    "title",
            "Price_euros": "price_eur",
            "Ram":        "ram",
            "Memory":     "storage",
        },
    },
    "muhammetvarl/gpu-prices": {
        "description": "Historial de precios de GPUs",
        "priority": 1,
        "expected_files": ["gpu_prices.csv"],
        "columns_map": {
            "name":  "title",
            "price": "price_usd",
            "date":  "price_date",
        },
    },
    "alanjo/pc-component-prices-history": {
        "description": "Historial de precios de componentes PC",
        "priority": 1,
        "expected_files": ["prices.csv"],
        "columns_map": {
            "product": "title",
            "price":   "price_usd",
            "date":    "price_date",
            "store":   "retailer",
        },
    },
}


# ──────────────────────────────────────────────
# SETUP KAGGLE API
# ──────────────────────────────────────────────

def _setup_kaggle_credentials() -> bool:
    """Configura las credenciales de Kaggle desde variables de entorno."""
    if not KAGGLE_USERNAME or not KAGGLE_KEY:
        logger.error(
            "❌ KAGGLE_USERNAME o KAGGLE_KEY no configurados. "
            "Obtén tu API key en: https://www.kaggle.com/settings → API → Create New Token"
        )
        return False

    # Crear ~/.kaggle/kaggle.json
    kaggle_dir = Path.home() / ".kaggle"
    kaggle_dir.mkdir(exist_ok=True)
    kaggle_json = kaggle_dir / "kaggle.json"

    credentials = {
        "username": KAGGLE_USERNAME,
        "key":      KAGGLE_KEY,
    }

    with open(kaggle_json, "w") as f:
        json.dump(credentials, f)

    kaggle_json.chmod(0o600)
    logger.info("✅ Credenciales Kaggle configuradas")
    return True


# ──────────────────────────────────────────────
# DESCARGA Y PROCESAMIENTO
# ──────────────────────────────────────────────

def _download_dataset(dataset_id: str, dest_dir: Path) -> Optional[Path]:
    """
    Descarga un dataset de Kaggle.
    Retorna el directorio donde se descomprimió, o None si falla.
    """
    try:
        import kaggle  # Import tardío — solo si las credenciales están OK
    except ImportError:
        logger.error("❌ kaggle no instalado. Ejecuta: pip install kaggle")
        return None

    dataset_dir = dest_dir / dataset_id.replace("/", "_")
    dataset_dir.mkdir(parents=True, exist_ok=True)

    try:
        logger.info(f"  📥 Descargando: {dataset_id}")
        kaggle.api.dataset_download_files(
            dataset_id,
            path=str(dataset_dir),
            unzip=True,
            quiet=False,
        )
        logger.info(f"  ✅ Descargado en: {dataset_dir}")
        return dataset_dir

    except Exception as e:
        logger.warning(f"  ⚠️ Error descargando {dataset_id}: {e}")
        return None


def _normalize_dataset(
    dataset_dir: Path,
    config: dict,
    dataset_id: str,
    batch_id: str,
) -> list:
    """
    Normaliza un dataset descargado al esquema estándar del proyecto.
    Retorna lista de registros normalizados.
    """
    records = []
    now_iso = datetime.now(timezone.utc).isoformat()
    columns_map = config.get("columns_map", {})
    filter_cats = config.get("filter_categories", [])

    # Buscar archivos CSV en el directorio descargado
    csv_files = list(dataset_dir.glob("**/*.csv"))
    if not csv_files:
        logger.warning(f"  ⚠️ No se encontraron CSVs en {dataset_dir}")
        return records

    for csv_file in csv_files:
        try:
            logger.info(f"  📄 Procesando: {csv_file.name}")
            df = pd.read_csv(csv_file, low_memory=False, on_bad_lines="skip")
            logger.info(f"     Filas: {len(df):,} | Columnas: {list(df.columns)[:8]}")

            # Renombrar columnas según el mapa
            rename_map = {
                orig: dest
                for orig, dest in columns_map.items()
                if orig in df.columns
            }
            if rename_map:
                df = df.rename(columns=rename_map)

            # Filtrar por categoría si aplica
            if filter_cats and "category" in df.columns:
                mask = df["category"].astype(str).str.contains(
                    "|".join(filter_cats), case=False, na=False
                )
                df = df[mask]
                logger.info(f"     Filtrado por categoría: {len(df):,} filas")

            # Asegurar columna de precio
            if "price_usd" not in df.columns:
                # Buscar cualquier columna de precio
                price_cols = [c for c in df.columns if "price" in c.lower()]
                if price_cols:
                    df = df.rename(columns={price_cols[0]: "price_usd"})

            # Limpiar precios
            if "price_usd" in df.columns:
                df["price_usd"] = (
                    df["price_usd"]
                    .astype(str)
