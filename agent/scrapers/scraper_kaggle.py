"""
scraper_kaggle.py
Descarga automática de datasets de hardware/electrónica desde Kaggle.

Requiere: KAGGLE_USERNAME + KAGGLE_KEY en secrets
Obtén tu API key en: https://www.kaggle.com/settings → API → Create New Token
"""

import os
import json
import logging
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

BASE_DIR     = Path(__file__).resolve().parent.parent.parent
DATA_RAW_DIR = BASE_DIR / "data" / "raw"
KAGGLE_DIR   = BASE_DIR / "data" / "kaggle"
KAGGLE_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────
# DATASETS OBJETIVO
# ──────────────────────────────────────────────
TARGET_DATASETS = {
    "asaniczka/amazon-products-dataset-2023-1-4m-products": {
        "description": "1.4M productos Amazon con precios (2023)",
        "priority": 1,
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
    },
    "promptcloud/amazon-product-dataset-2020": {
        "description": "Productos Amazon con precios y ratings (2020)",
        "priority": 1,
        "columns_map": {
            "product_name":  "title",
            "selling_price": "price_usd",
            "category":      "category",
        },
        "filter_categories": [],
    },
    "thedevastator/the-ultimate-laptop-price-predictor": {
        "description": "Dataset de laptops con specs y precios",
        "priority": 1,
        "columns_map": {
            "Company": "brand",
            "Product": "title",
            "Ram":     "ram",
            "Memory":  "storage",
        },
        "filter_categories": [],
    },
    "muhammetvarl/gpu-prices": {
        "description": "Historial de precios de GPUs",
        "priority": 1,
        "columns_map": {
            "name":  "title",
            "price": "price_usd",
            "date":  "price_date",
        },
        "filter_categories": [],
    },
    "iliassekkaf/pc-hardware-prices": {
        "description": "Precios históricos de componentes PC",
        "priority": 1,
        "columns_map": {
            "name":     "title",
            "price":    "price_usd",
            "date":     "price_date",
            "category": "category",
        },
        "filter_categories": [],
    },
    "PromptCloudHQ/flipkart-products": {
        "description": "Productos Flipkart — referencia precios Asia",
        "priority": 2,
        "columns_map": {
            "product_name":     "title",
            "discounted_price": "price_usd",
            "product_category_tree": "category",
        },
        "filter_categories": [],
    },
}


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
# DESCARGA
# ──────────────────────────────────────────────

def _download_dataset(dataset_id: str) -> Optional[Path]:
    try:
        import kaggle
    except ImportError:
        logger.error("❌ kaggle no instalado. Ejecuta: pip install kaggle")
        return None

    dest = KAGGLE_DIR / dataset_id.replace("/", "_")
    dest.mkdir(parents=True, exist_ok=True)

    try:
        logger.info(f"  📥 Descargando: {dataset_id}")
        kaggle.api.dataset_download_files(
            dataset_id, path=str(dest), unzip=True, quiet=False
        )
        logger.info(f"  ✅ Descargado en: {dest}")
        return dest
    except Exception as e:
        logger.warning(f"  ⚠️ Error descargando {dataset_id}: {e}")
        return None


# ──────────────────────────────────────────────
# NORMALIZACIÓN
# ──────────────────────────────────────────────

def _clean_price(series: pd.Series) -> pd.Series:
    """Limpia columna de precio: elimina símbolos, convierte a float."""
    return (
        series
        .astype(str)
        .str.replace(r"[^\d.]", "", regex=True)
        .str.strip()
        .replace("", "0")
        .astype(float)
    )


def _normalize_dataset(
    dataset_dir: Path,
    config: dict,
    dataset_id: str,
    batch_id: str,
) -> list:
    records     = []
    now_iso     = datetime.now(timezone.utc).isoformat()
    columns_map = config.get("columns_map", {})
    filter_cats = config.get("filter_categories", [])

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

            # Renombrar columnas
            rename_map = {
                orig: dest
                for orig, dest in columns_map.items()
                if orig in df.columns
            }
            if rename_map:
                df = df.rename(columns=rename_map)

            # Filtrar por categoría
            if filter_cats and "category" in df.columns:
                mask = df["category"].astype(str).str.contains(
                    "|".join(filter_cats), case=False, na=False
                )
                df   = df[mask].copy()
                logger.info(f"     Filtrado: {len(df):,} filas")

            # Limpiar precio
            if "price_usd" not in df.columns:
                price_cols = [c for c in df.columns if "price" in c.lower()]
                if price_cols:
                    df = df.rename(columns={price_cols[0]: "price_usd"})

            if "price_usd" in df.columns:
                df["price_usd"] = _clean_price(df["price_usd"])
                df = df[df["price_usd"] > 0]

            # Agregar columnas de metadata
            df["batch_id"]   = batch_id
            df["timestamp"]  = now_iso
            df["source"]     = f"kaggle_{dataset_id.split('/')[1][:20]}"
            df["price_date"] = df.get("price_date", now_iso[:10])

            # Asegurar columna title
            if "title" not in df.columns:
                title_cols = [c for c in df.columns if "name" in c.lower() or "title" in c.lower()]
                if title_cols:
                    df = df.rename(columns={title_cols[0]: "title"})

            # Convertir a lista de dicts (máx 50k por dataset para no explotar RAM)
            subset = df.head(50_000)
            batch  = subset.to_dict(orient="records")
            records.extend(batch)
            logger.info(f"     ✅ {len(batch):,} registros normalizados")

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
    Si no hay credenciales, retorna lista vacía sin fallar.
    """
    if not _setup_kaggle_credentials():
        logger.warning("[Kaggle] Sin credenciales — saltando")
        return []

    all_records = []

    # Ordenar por prioridad
    sorted_datasets = sorted(
        TARGET_DATASETS.items(),
        key=lambda x: x[1].get("priority", 99)
    )

    for dataset_id, config in sorted_datasets:
        logger.info(f"\n[Kaggle] Dataset: {dataset_id}")
        logger.info(f"  {config['description']}")

        dataset_dir = _download_dataset(dataset_id)
        if dataset_dir is None:
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
    batch = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    results = scrape_kaggle(batch)
    print(f"\nTotal: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
