#!/usr/bin/env python3
"""
data_quality.py v1.0
<<<<<<< HEAD
Etapa I del pipeline — data_quality -> temporal_split -> mice_imputer -> feature_engineering
[DQ1] validate_schema | [DQ2] validate_completeness | [DQ3] filter_price_outliers
[DQ4] normalize_categories | [DQ5] normalize_sources | [DQ6] normalize_price_date
[DQ7] deduplicate | [DQ8] generate_report
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

CATEGORY_MAP = {
    "discos_ssd":"SSD","ssd":"SSD","memorias_ram":"RAM","ram":"RAM",
    "procesadores":"CPU","cpu":"CPU","tarjetas_video":"GPU","gpu":"GPU",
    "monitores":"MONITOR","monitor":"MONITOR","teclados":"TECLADO",
    "mouse":"MOUSE","auriculares":"AURICULAR","parlantes":"PARLANTE",
    "computadoras":"PC","laptops":"LAPTOP","tablets":"TABLET",
    "celulares":"CELULAR","smartwatch":"SMARTWATCH",
    "videojuegos":"VIDEOJUEGO","televisores":"TV","impresoras":"IMPRESORA",
    "cooler":"COOLER","motherboard":"MOTHERBOARD","psu":"PSU","case":"CASE",
}
SOURCE_MAP = {
    "falabella":"falabella_pe","hiraoka":"hiraoka_pe",
    "falabella_benchmark":"falabella_pe","hiraoka_benchmark":"hiraoka_pe",
}
REQUIRED_COLUMNS = ["source","category","title","price_usd","price_pen","price_date"]
COMPLETENESS_THRESHOLDS = {
    "price_usd":75.0,"price_pen":65.0,"price_date":99.0,
    "source":100.0,"title":99.0,"category":95.0,"sku":75.0,"brand":70.0,
}
PRICE_MAX_PEN = 50_000.0
PRICE_MAX_USD = 15_000.0

def validate_schema(df):
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        print(f"\n FATAL [DQ1]: columnas obligatorias ausentes: {missing}")
        sys.exit(1)
    print(f"  [DQ1] OK Esquema OK — {len(REQUIRED_COLUMNS)} columnas obligatorias presentes")

def validate_completeness(df):
    stats, warns = {}, []
    for col, thr in COMPLETENESS_THRESHOLDS.items():
        if col not in df.columns: continue
        pct = round((1 - df[col].isna().mean()) * 100, 2)
        stats[col] = pct
        if pct < thr:
            warns.append(f"    WARN {col}: {pct}% completo (minimo: {thr}%)")
    if warns:
        print(f"  [DQ2] WARN Completitud baja en {len(warns)} columna(s):")
        for w in warns: print(w)
    else:
        print(f"  [DQ2] OK Completitud OK en todas las columnas")
    return stats

def filter_price_outliers(df):
    n0 = len(df)
    mask = (df["price_pen"] <= 0) | (df["price_usd"] <= 0) | \
           (df["price_pen"] > PRICE_MAX_PEN) | (df["price_usd"] > PRICE_MAX_USD)
    df = df[~mask].copy()
    print(f"  [DQ3] Outliers eliminados: {n0-len(df):,} filas | Rango PEN: S/{df['price_pen'].min():.2f}-{df['price_pen'].max():.2f}")
    return df

def normalize_categories(df):
    df = df.copy()
    b = df["category"].nunique()
    df["category"] = df["category"].str.strip().str.lower().map(
        lambda x: CATEGORY_MAP.get(x, x.upper() if isinstance(x,str) else x))
    print(f"  [DQ4] Categorias: {b} -> {df['category'].nunique()} unicas")
    print(f"         {df['category'].value_counts().to_dict()}")
    return df

def normalize_sources(df):
    df = df.copy()
    b = df["source"].nunique()
    df["source"] = df["source"].map(lambda x: SOURCE_MAP.get(x,x) if isinstance(x,str) else x)
    print(f"  [DQ5] Fuentes: {b} -> {df['source'].nunique()} unicas")
    print(f"         {df['source'].value_counts().to_dict()}")
    return df

def normalize_price_date(df):
    df = df.copy()
    parsed = pd.to_datetime(df["price_date"], errors="coerce")
    n_inv = int(parsed.isna().sum())
    if n_inv > 0:
        print(f"  [DQ6] WARN {n_inv:,} filas con price_date invalida -> eliminadas")
        df = df[parsed.notna()].copy()
        parsed = parsed[parsed.notna()]
    df["price_date"] = parsed.dt.strftime("%Y-%m-%d")
    print(f"  [DQ6] OK price_date ISO 8601 — rango: {df['price_date'].min()} -> {df['price_date'].max()}")
    return df

def deduplicate(df):
    n0 = len(df)
=======
═══════════════════════════════════════════════════════════════════
Etapa I del pipeline (previa a temporal_split.py).

Valida, limpia y normaliza el MASTER_hardware_peru_clean.csv antes
de que entre al pipeline de partición temporal y modelado.

ORDEN EN EL PIPELINE:
  **data_quality.py** → temporal_split.py → mice_imputer.py →
  feature_engineering.py

MÓDULOS:
  [DQ1] validate_schema()        — columnas obligatorias (fail-fast)
  [DQ2] validate_completeness()  — % NaN vs umbrales del contrato
  [DQ3] filter_price_outliers()  — elimina precios anómalos
  [DQ4] normalize_categories()   — unifica nombres duplicados
  [DQ5] normalize_sources()      — unifica nombres de fuentes
  [DQ6] normalize_price_date()   — ISO 8601 uniforme (requerido por [T2])
  [DQ7] deduplicate()            — elimina duplicados por fingerprint
  [DQ8] generate_report()        — quality_report_<batch>.json

Uso:
    python preprocessing/data_quality.py \
        --input  data/processed/MASTER_hardware_peru_clean.csv \
        --output data/processed/MASTER_hardware_peru_clean.csv \
        --report-dir data/processed
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


# ══════════════════════════════════════════════════════════════════
# CONSTANTES DE NORMALIZACIÓN
# ══════════════════════════════════════════════════════════════════

CATEGORY_MAP = {
    # SSD
    "discos_ssd": "SSD",
    "ssd":        "SSD",
    # RAM
    "memorias_ram": "RAM",
    "ram":          "RAM",
    # CPU
    "procesadores": "CPU",
    "cpu":          "CPU",
    # GPU
    "tarjetas_video": "GPU",
    "gpu":            "GPU",
    # Monitores
    "monitores":  "MONITOR",
    "monitor":    "MONITOR",
    # Periféricos
    "teclados":   "TECLADO",
    "mouse":      "MOUSE",
    "auriculares":"AURICULAR",
    "parlantes":  "PARLANTE",
    # Computadoras
    "computadoras":  "PC",
    "laptops":       "LAPTOP",
    "tablets":       "TABLET",
    "celulares":     "CELULAR",
    "smartwatch":    "SMARTWATCH",
    "videojuegos":   "VIDEOJUEGO",
    "televisores":   "TV",
    "impresoras":    "IMPRESORA",
}

SOURCE_MAP = {
    "falabella":           "falabella_pe",
    "hiraoka":             "hiraoka_pe",
    "falabella_benchmark": "falabella_pe",
    "hiraoka_benchmark":   "hiraoka_pe",
}

# Columnas núcleo — fail-fast si no existen
REQUIRED_COLUMNS = ["source", "category", "title", "price_usd", "price_pen", "price_date"]

# Umbrales de completitud mínima por columna (del data_contract.yaml v1.1)
COMPLETENESS_THRESHOLDS = {
    "price_usd":  99.0,
    "price_pen":  99.0,
    "price_date": 99.0,
    "source":     100.0,
    "title":      99.0,
    "category":   95.0,
    "sku":        75.0,   # 19.83% NaN aceptado — limitación conocida
    "brand":      70.0,
}

# Umbrales de precio para outliers
PRICE_MAX_PEN = 50_000.0   # S/ 50,000 — máximo razonable hardware Perú
PRICE_MAX_USD = 15_000.0   # USD 15,000


# ══════════════════════════════════════════════════════════════════
# [DQ1] VALIDACIÓN DE ESQUEMA — fail-fast
# ══════════════════════════════════════════════════════════════════
def validate_schema(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        print(f"\n❌ FATAL [DQ1]: columnas obligatorias ausentes: {missing}")
        print("   Revisar el scraper o data_contract.yaml antes de continuar.")
        sys.exit(1)
    print(f"  [DQ1] ✅ Esquema OK — {len(REQUIRED_COLUMNS)} columnas obligatorias presentes")


# ══════════════════════════════════════════════════════════════════
# [DQ2] VALIDACIÓN DE COMPLETITUD
# ══════════════════════════════════════════════════════════════════
def validate_completeness(df: pd.DataFrame) -> dict:
    stats = {}
    warnings_found = []
    for col, threshold in COMPLETENESS_THRESHOLDS.items():
        if col not in df.columns:
            continue
        completeness = round((1 - df[col].isna().mean()) * 100, 2)
        stats[col] = completeness
        if completeness < threshold:
            warnings_found.append(
                f"    ⚠️  {col}: {completeness}% completo (mínimo: {threshold}%)"
            )
    if warnings_found:
        print(f"  [DQ2] ⚠️  Completitud por debajo del umbral en {len(warnings_found)} columna(s):")
        for w in warnings_found:
            print(w)
    else:
        print(f"  [DQ2] ✅ Completitud OK en todas las columnas monitoreadas")
    return stats


# ══════════════════════════════════════════════════════════════════
# [DQ3] FILTRO DE OUTLIERS DE PRECIO
# ══════════════════════════════════════════════════════════════════
def filter_price_outliers(df: pd.DataFrame) -> pd.DataFrame:
    n_before = len(df)

    # Precios negativos o cero
    mask_invalid = (df["price_pen"] <= 0) | (df["price_usd"] <= 0)
    n_invalid = int(mask_invalid.sum())

    # Precios extremos
    mask_extreme = (df["price_pen"] > PRICE_MAX_PEN) | (df["price_usd"] > PRICE_MAX_USD)
    n_extreme = int(mask_extreme.sum())

    df = df[~mask_invalid & ~mask_extreme].copy()
    n_after = len(df)

    print(f"  [DQ3] Outliers de precio eliminados: {n_before - n_after:,} filas")
    print(f"         Inválidos (<=0): {n_invalid:,} | Extremos: {n_extreme:,}")
    print(f"         Rango final — PEN: S/ {df['price_pen'].min():.2f}–{df['price_pen'].max():.2f} "
          f"| USD: ${df['price_usd'].min():.2f}–{df['price_usd'].max():.2f}")
    return df


# ══════════════════════════════════════════════════════════════════
# [DQ4] NORMALIZACIÓN DE CATEGORÍAS
# ══════════════════════════════════════════════════════════════════
def normalize_categories(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    before = df["category"].nunique()
    df["category"] = (
        df["category"]
        .str.strip()
        .str.lower()
        .map(lambda x: CATEGORY_MAP.get(x, x.upper() if isinstance(x, str) else x))
    )
    after = df["category"].nunique()
    print(f"  [DQ4] Categorías normalizadas: {before} → {after} categorías únicas")
    print(f"         Distribución: {df['category'].value_counts().to_dict()}")
    return df


# ══════════════════════════════════════════════════════════════════
# [DQ5] NORMALIZACIÓN DE FUENTES
# ══════════════════════════════════════════════════════════════════
def normalize_sources(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    before = df["source"].nunique()
    df["source"] = df["source"].map(
        lambda x: SOURCE_MAP.get(x, x) if isinstance(x, str) else x
    )
    after = df["source"].nunique()
    print(f"  [DQ5] Fuentes normalizadas: {before} → {after} fuentes únicas")
    print(f"         Distribución: {df['source'].value_counts().to_dict()}")
    return df


# ══════════════════════════════════════════════════════════════════
# [DQ6] NORMALIZACIÓN DE FECHA — ISO 8601 YYYY-MM-DD
# ══════════════════════════════════════════════════════════════════
def normalize_price_date(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    parsed = pd.to_datetime(df["price_date"], errors="coerce")
    n_invalid = int(parsed.isna().sum())

    if n_invalid > 0:
        pct = round(n_invalid / len(df) * 100, 3)
        print(f"  [DQ6] ⚠️  {n_invalid:,} filas ({pct}%) con price_date no parseable → se eliminan")
        df = df[parsed.notna()].copy()
        parsed = parsed[parsed.notna()]

    df["price_date"] = parsed.dt.strftime("%Y-%m-%d")
    print(f"  [DQ6] ✅ price_date normalizado a ISO 8601 — rango: "
          f"{df['price_date'].min()} → {df['price_date'].max()}")
    return df


# ══════════════════════════════════════════════════════════════════
# [DQ7] DEDUPLICACIÓN
# ══════════════════════════════════════════════════════════════════
def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    n_before = len(df)

>>>>>>> 2ccc6fc652bb1c88a3f49e1bad3341891633d8ea
    if "fingerprint" in df.columns and df["fingerprint"].notna().sum() > 0:
        df = df.drop_duplicates(subset=["fingerprint"], keep="last")
        method = "fingerprint"
    else:
<<<<<<< HEAD
        keys = [c for c in ["source","sku","price_date","price_usd"] if c in df.columns]
        df = df.drop_duplicates(subset=keys, keep="last")
        method = f"clave compuesta {keys}"
    print(f"  [DQ7] Duplicados: {n0-len(df):,} eliminados ({method}) | {n0:,} -> {len(df):,}")
    return df.reset_index(drop=True)

def generate_report(df_before, df_after, completeness_stats, report_dir):
=======
        key_cols = ["source", "sku", "price_date", "price_usd"]
        available = [c for c in key_cols if c in df.columns]
        df = df.drop_duplicates(subset=available, keep="last")
        method = f"clave compuesta ({available})"

    n_after = len(df)
    print(f"  [DQ7] Duplicados eliminados: {n_before - n_after:,} filas (método: {method})")
    print(f"         {n_before:,} → {n_after:,} filas")
    return df.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════
# [DQ8] REPORTE JSON DE CALIDAD
# ══════════════════════════════════════════════════════════════════
def generate_report(
    df_before: pd.DataFrame,
    df_after: pd.DataFrame,
    completeness_stats: dict,
    report_dir: Path,
) -> dict:
>>>>>>> 2ccc6fc652bb1c88a3f49e1bad3341891633d8ea
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report = {
        "batch_id": batch_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_step": "data_quality.py v1.0",
<<<<<<< HEAD
        "rows_before": int(len(df_before)),
        "rows_after": int(len(df_after)),
        "rows_removed": int(len(df_before)-len(df_after)),
        "pct_retained": round(len(df_after)/max(len(df_before),1)*100, 2),
        "completeness_pct": completeness_stats,
        "category_distribution": df_after["category"].value_counts().to_dict(),
        "source_distribution": df_after["source"].value_counts().to_dict(),
        "price_range": {
            "pen_min": float(df_after["price_pen"].min()),
            "pen_max": float(df_after["price_pen"].max()),
            "pen_median": float(df_after["price_pen"].median()),
            "usd_min": float(df_after["price_usd"].min()),
            "usd_max": float(df_after["price_usd"].max()),
            "usd_median": float(df_after["price_usd"].median()),
        },
        "date_range": {
            "min": df_after["price_date"].min(),
            "max": df_after["price_date"].max(),
            "unique_dates": int(pd.to_datetime(df_after["price_date"]).nunique()),
        },
    }
    path = report_dir / f"quality_report_{batch_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"  [DQ8] OK Reporte guardado: {path.name}")
    return report

def run_data_quality(input_path, output_path, report_dir):
    report_dir.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("  DATA QUALITY v1.0 - Etapa I")
    print("=" * 60)
    df = pd.read_csv(input_path, low_memory=False)
    df_before = df.copy()
    print(f"\n MASTER cargado: {len(df):,} filas | {df.shape[1]} columnas")
    print("\n-- Validaciones --")
    validate_schema(df)
    completeness_stats = validate_completeness(df)
    print("\n-- Limpieza --")
=======
        "rows_before":  int(len(df_before)),
        "rows_after":   int(len(df_after)),
        "rows_removed": int(len(df_before) - len(df_after)),
        "pct_retained": round(len(df_after) / max(len(df_before), 1) * 100, 2),
        "columns_before": int(df_before.shape[1]),
        "columns_after":  int(df_after.shape[1]),
        "completeness_pct": completeness_stats,
        "category_distribution": df_after["category"].value_counts().to_dict(),
        "source_distribution":   df_after["source"].value_counts().to_dict(),
        "price_range": {
            "pen_min":    float(df_after["price_pen"].min()),
            "pen_max":    float(df_after["price_pen"].max()),
            "pen_median": float(df_after["price_pen"].median()),
            "usd_min":    float(df_after["price_usd"].min()),
            "usd_max":    float(df_after["price_usd"].max()),
            "usd_median": float(df_after["price_usd"].median()),
        },
        "date_range": {
            "min":          df_after["price_date"].min(),
            "max":          df_after["price_date"].max(),
            "unique_dates": int(pd.to_datetime(df_after["price_date"]).nunique()),
        },
    }

    report_path = report_dir / f"quality_report_{batch_id}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(f"  [DQ8] ✅ Reporte guardado: {report_path.name}")
    return report


# ══════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════════════════
def run_data_quality(
    input_path: Path,
    output_path: Path,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)

    print("═" * 60)
    print("  DATA QUALITY v1.0 — Etapa I")
    print("═" * 60)

    df = pd.read_csv(input_path, low_memory=False)
    df_before = df.copy()
    print(f"\n📊 MASTER cargado: {len(df):,} filas | {df.shape[1]} columnas")

    print("\n── Validaciones ──────────────────────────────────────────")
    validate_schema(df)
    completeness_stats = validate_completeness(df)

    print("\n── Limpieza ──────────────────────────────────────────────")
>>>>>>> 2ccc6fc652bb1c88a3f49e1bad3341891633d8ea
    df = filter_price_outliers(df)
    df = normalize_categories(df)
    df = normalize_sources(df)
    df = normalize_price_date(df)
    df = deduplicate(df)
<<<<<<< HEAD
    n_rem = len(df_before) - len(df)
    print(f"\n-- Resultado final --")
    print(f"  Antes  : {len(df_before):,} | Despues: {len(df):,} | Eliminadas: {n_rem:,} ({round(n_rem/len(df_before)*100,2)}%)")
    df.to_csv(output_path, index=False)
    print(f"\n OK MASTER limpio guardado: {output_path}")
    generate_report(df_before, df, completeness_stats, report_dir)
    print("\n" + "=" * 60)
    print("  OK data_quality.py completado — listo para temporal_split.py")
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/processed/MASTER_hardware_peru_clean.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/MASTER_hardware_peru_clean.csv"))
    parser.add_argument("--report-dir", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    run_data_quality(args.input, args.output, args.report_dir)
=======

    print("\n── Resultado final ───────────────────────────────────────")
    n_removed = len(df_before) - len(df)
    pct_removed = round(n_removed / len(df_before) * 100, 2)
    print(f"  Filas antes  : {len(df_before):,}")
    print(f"  Filas después: {len(df):,}")
    print(f"  Eliminadas   : {n_removed:,} ({pct_removed}%)")

    df.to_csv(output_path, index=False)
    print(f"\n✅ MASTER limpio guardado en: {output_path}")

    generate_report(df_before, df, completeness_stats, report_dir)

    print("\n" + "═" * 60)
    print("  ✅ data_quality.py completado — listo para temporal_split.py")
    print("═" * 60)


# ══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="data_quality.py v1.0 — Validación y limpieza del MASTER"
    )
    parser.add_argument(
        "--input", type=Path,
        default=Path("data/processed/MASTER_hardware_peru_clean.csv"),
        help="Ruta al MASTER CSV de entrada",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/processed/MASTER_hardware_peru_clean.csv"),
        help="Ruta de salida del MASTER limpio (puede ser igual al input)",
    )
    parser.add_argument(
        "--report-dir", type=Path,
        default=Path("data/processed"),
        help="Directorio donde se guarda el quality_report_<batch>.json",
    )
    args = parser.parse_args()
    run_data_quality(
        input_path=args.input,
        output_path=args.output,
        report_dir=args.report_dir,
    )
>>>>>>> 2ccc6fc652bb1c88a3f49e1bad3341891633d8ea
