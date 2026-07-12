"""
scraper_kaggle.py  v3.1
════════════════════════
Descarga automática de datasets de hardware/electrónica desde Kaggle.

Fixes v3.1 (sobre v3.0):
  [K7]  scrape_kaggle(): parámetro mode agregado — alinea firma con main.py
        (main.py pasa mode= a todos los scrapers)
  [K8]  _normalize_dataset(): price_usd validado con rango mínimo/máximo
        (PRICE_MIN_USD=0.5, PRICE_MAX_USD=15000.0) — evita que precios
        absurdos post-conversión (INR×0.012) contaminen el MASTER
  [K9]  _is_cached(): datetime.now(timezone.utc) — naive datetime corregido
        (consistente con [D2] de scraper_dolar)
  [K10] scrape_kaggle(): log de tiempo total al finalizar
        (consistente con [M4]/[M18] del resto de scrapers)
  [K11] _normalize_dataset(): log WARNING cuando price_usd mediana < 1.0 USD
        — indica posible error de conversión de moneda (fx_rate incorrecto)
"""

import os
import re
import json
import logging
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

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

CACHE_MAX_AGE_DAYS = 7

# [K8] Rango de precio válido post-conversión a USD
PRICE_MIN_USD = 0.5
PRICE_MAX_USD = 15_000.0

# [K2] Tasas de conversión fijas a USD — actualizar trimestralmente
# Fuente: promedio histórico 2024-2026
FX_TO_USD = {
    "USD": 1.0,
    "EUR": 1.08,    # 1 EUR ≈ 1.08 USD
    "INR": 0.012,   # 1 INR ≈ 0.012 USD (₹83/USD)
    "GBP": 1.27,
    "JPY": 0.0067,
}

# ──────────────────────────────────────────────
# TARGET_DATASETS
# [K5] max_rows reducidos — total ~70k (era 330k)
# [K1] brendan45774/computer-parts → promptcloud/product-details-on-amazon
# ──────────────────────────────────────────────
TARGET_DATASETS = {
    "asaniczka/amazon-products-dataset-2023-1-4m-products": {
        "alias":       "amazon_2023",
        "description": "1.4M productos Amazon con precios (2023)",
        "priority":    1,
        "max_rows":    20_000,   # [K5]
        "columns_map": {
            "title":        "title",
            "price":        "price_local",
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
        "max_rows":    10_000,   # [K5]
        "columns_map": {
            "product_name":  "title",
            "selling_price": "price_local",
            "category":      "category",
        },
        "filter_categories": [],
        "price_currency": "USD",
    },
    "thedevastator/laptop-prices-dataset": {
        "alias":       "laptops_specs",
        "description": "Laptops con specs y precios en euros",
        "priority":    1,
        "max_rows":    10_000,   # [K5]
        "columns_map": {
            "Company":     "brand",
            "Product":     "title",
            "Ram":         "ram",
            "Memory":      "storage",
            "Price_euros": "price_local",
            "Price":       "price_local",
        },
        "filter_categories": [],
        "price_currency": "EUR",   # [K2] se convierte a USD
    },
    "muhammetvarl/gpu-prices": {
        "alias":       "gpu_prices",
        "description": "Historial de precios de GPUs",
        "priority":    1,
        "max_rows":    10_000,   # [K5]
        "columns_map": {
            "name":  "title",
            "price": "price_local",
            "date":  "price_date",
        },
        "filter_categories": [],
        "price_currency": "USD",
    },
    # [K1] Reemplazado brendan45774/computer-parts (baja visibilidad)
    "promptcloud/product-details-on-amazon": {
        "alias":       "amazon_pc_parts",
        "description": "Componentes PC en Amazon USA — dataset verificado",
        "priority":    1,
        "max_rows":    10_000,   # [K5]
        "columns_map": {
            "product_name":  "title",
            "selling_price": "price_local",
            "category":      "category",
        },
        "filter_categories": [],
        "price_currency": "USD",
    },
    "promptcloudhq/flipkart-products": {
        "alias":       "flipkart",
        "description": "Productos Flipkart — referencia precios Asia (rupias→USD)",
        "priority":    2,
        "max_rows":    10_000,   # [K5]
        "columns_map": {
            "product_name":          "title",
            "discounted_price":      "price_local",
            "product_category_tree": "category",
        },
        "filter_categories": [],
        "price_currency": "INR",   # [K2] se convierte a USD
    },
}


# ──────────────────────────────────────────────
# Parser de precios robusto
# ──────────────────────────────────────────────
def _parse_price_str(text: str) -> Optional[float]:
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
                clean = clean.replace(",", ".")
            else:
                clean = clean.replace(",", "")
        val = float(clean)
        return val if val > 0 else None
    except ValueError:
        return None

def _clean_price_series(series: pd.Series) -> pd.Series:
    return series.map(_parse_price_str)


# ──────────────────────────────────────────────
# Setup credenciales
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
# Caché de descarga
# ──────────────────────────────────────────────
def _is_cached(dest: Path) -> bool:
    csv_files = list(dest.glob("**/*.csv"))
    if not csv_files:
        return False
    newest_mtime = max(f.stat().st_mtime for f in csv_files)
    # [K9] Usar timestamp UTC — evita naive datetime
    age_days = (
        datetime.now(timezone.utc).timestamp() - newest_mtime
    ) / 86400
    if age_days < CACHE_MAX_AGE_DAYS:
        logger.info(
            f"  📦 Cache hit: {dest.name} ({age_days:.1f}d de antigüedad)"
        )
        return True
    return False


# ──────────────────────────────────────────────
# Descarga
# ──────────────────────────────────────────────
def _download_dataset(dataset_id: str) -> Optional[Path]:
    if not KAGGLE_AVAILABLE or kaggle_lib is None:
        logger.error("❌ kaggle no instalado. Ejecuta: pip install kaggle")
        return None
    dest = KAGGLE_DIR / dataset_id.replace("/", "_")
    dest.mkdir(parents=True, exist_ok=True)
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
        if list(dest.glob("**/*.csv")):
            logger.info(f"  ♻️ Usando datos anteriores de {dest.name}")
            return dest
        return None


# ──────────────────────────────────────────────
# Normalización
# ──────────────────────────────────────────────
def _normalize_dataset(
    dataset_dir: Path,
    config: dict,
    dataset_id: str,
    batch_id: str,
) -> list:
    records        = []
    now_iso        = datetime.now(timezone.utc).isoformat()
    columns_map    = config.get("columns_map", {})
    filter_cats    = config.get("filter_categories", [])
    alias          = config.get("alias", dataset_id.split("/")[1])
    max_rows       = config.get("max_rows", 10_000)
    price_currency = config.get("price_currency", "USD")
    # [K2] Factor de conversión a USD
    fx_rate        = FX_TO_USD.get(price_currency, 1.0)

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
            logger.info(
                f"     Filas: {len(df):,} | Cols: {list(df.columns[:6])}"
            )

            # Renombrar columnas — evita mapear dos al mismo destino
            rename_map = {}
            for orig, dest_col in columns_map.items():
                if orig in df.columns and dest_col not in rename_map.values():
                    rename_map[orig] = dest_col
            if rename_map:
                df = df.rename(columns=rename_map)

            # Filtrar por categoría
            if filter_cats and "category" in df.columns:
                pattern = "|".join(re.escape(c) for c in filter_cats)
                mask    = df["category"].astype(str).str.contains(
                    pattern, case=False, na=False
                )
                df = df[mask].copy()
                logger.info(f"     Filtrado: {len(df):,} filas")

            # Detectar columna de precio si no fue mapeada
            if "price_local" not in df.columns:
                price_cols = [c for c in df.columns if "price" in c.lower()]
                if price_cols:
                    df = df.rename(columns={price_cols[0]: "price_local"})

            # Limpiar precio con parser robusto
            if "price_local" in df.columns:
                df["price_local"] = _clean_price_series(df["price_local"])
                df = df[df["price_local"].notna() & (df["price_local"] > 0)]

            # [K2] Convertir a USD usando tasa fija
            if "price_local" in df.columns:
                df["price_usd"] = (df["price_local"] * fx_rate).round(2)
            else:
                df["price_usd"] = None

            # [K8] Filtrar precios fuera de rango post-conversión
            if "price_usd" in df.columns and df["price_usd"].notna().any():
                before = len(df)
                df = df[
                    df["price_usd"].notna() &
                    (df["price_usd"] >= PRICE_MIN_USD) &
                    (df["price_usd"] <= PRICE_MAX_USD)
                ]
                filtered_out = before - len(df)
                if filtered_out > 0:
                    logger.info(
                        f"     [K8] {filtered_out:,} filas descartadas "
                        f"(price_usd fuera de "
                        f"[{PRICE_MIN_USD}, {PRICE_MAX_USD}])"
                    )

            # Asegurar columna title
            if "title" not in df.columns:
                title_cols = [
                    c for c in df.columns
                    if "name" in c.lower() or "title" in c.lower()
                ]
                if title_cols:
                    df = df.rename(columns={title_cols[0]: "title"})

            if "price_date" not in df.columns:
                df["price_date"] = now_iso[:10]

            # Metadata
            df["batch_id"]       = batch_id
            df["timestamp"]      = now_iso
            df["source"]         = f"kaggle_{alias}"
            df["price_currency"] = price_currency
            df["fx_rate_used"]   = fx_rate   # [K2] auditoría

            # [K3] Muestra representativa aleatoria
            n_sample = min(max_rows, len(df))
            subset   = df.sample(n=n_sample, random_state=42)

            # [K4] Reemplazar NaN con None antes de to_dict
            subset_clean = subset.where(subset.notna(), other=None)
            batch        = subset_clean.to_dict(orient="records")

            # [K11] Advertir si mediana de price_usd < 1.0 — posible fx error
            if "price_usd" in df.columns and df["price_usd"].notna().any():
                median_usd = df["price_usd"].median()
                if median_usd < 1.0:
                    logger.warning(
                        f"     ⚠️ [K11] Mediana price_usd={median_usd:.4f} USD "
                        f"< 1.0 — posible error de conversión "
                        f"(currency={price_currency}, fx={fx_rate})"
                    )
                logger.info(
                    f"     ✅ {len(batch):,} registros "
                    f"(currency={price_currency}, fx={fx_rate}, "
                    f"price_usd_mediana={median_usd:.2f} USD)"
                )
            else:
                logger.info(
                    f"     ✅ {len(batch):,} registros "
                    f"(currency={price_currency}, fx={fx_rate})"
                )

            records.extend(batch)

        except Exception as e:
            logger.warning(f"  ⚠️ Error procesando {csv_file.name}: {e}")
            continue

    return records


# ──────────────────────────────────────────────
# SCRAPER PRINCIPAL
# ──────────────────────────────────────────────
def scrape_kaggle(batch_id: str, mode: str = "normal") -> list:
    """
    Descarga y normaliza datasets de Kaggle.
    Retorna lista de registros con price_usd siempre en USD.
    Si no hay credenciales, retorna [] sin fallar.

    [K7]  Parámetro mode agregado — main.py lo pasa a todos los scrapers.
    [K10] Log de tiempo total al finalizar.

    NOTA: data/kaggle/ debe estar en .gitignore — archivos >100MB.
    """
    t_start = time.time()   # [K10]

    KAGGLE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)

    if not _setup_kaggle_credentials():
        logger.warning("[Kaggle] Sin credenciales — saltando")
        return []

    if not KAGGLE_AVAILABLE:
        logger.error(
            "[Kaggle] Librería 'kaggle' no instalada — pip install kaggle"
        )
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

    # [K10] Log de tiempo total
    elapsed = time.time() - t_start
    logger.info(
        f"\n[Kaggle] TOTAL: {len(all_records):,} registros — "
        f"⏱ {elapsed/60:.1f} min"
    )
    return all_records


# ──────────────────────────────────────────────
# STANDALONE
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # [K6] datetime con timezone explícita
    batch   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results = scrape_kaggle(batch)
    print(f"\nTotal: {len(results)}")
    if results:
        print("Ejemplo:", results[0])
