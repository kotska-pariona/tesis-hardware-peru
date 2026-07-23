#!/usr/bin/env python3
"""
data_quality.py v1.1
Etapa I del pipeline - data_quality -> temporal_split -> mice_imputer -> feature_engineering
[DQ1] validate_schema | [DQ2] validate_completeness | [DQ3] filter_price_outliers
[DQ4] normalize_categories | [DQ5] normalize_sources | [DQ6] normalize_price_date
[DQ7] deduplicate | [DQ8] consolidate_columns | [DQ9] generate_report
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

CATEGORY_MAP = {
    # SSD
    "discos_ssd": "SSD", "ssd": "SSD",
    # RAM
    "memorias_ram": "RAM", "ram": "RAM",
    # CPU
    "procesadores": "CPU", "cpu": "CPU",
    "peripheral": "PERIFERICO",
    "storage": "SSD",
    # GPU
    "tarjetas_video": "GPU", "gpu": "GPU",
    # MONITOR
    "monitores": "MONITOR", "monitor": "MONITOR",
    # TECLADO
    "teclados": "TECLADO", "teclado": "TECLADO",
    # MOUSE
    "mouse": "MOUSE",
    # AURICULAR
    "auriculares": "AURICULAR", "auricular": "AURICULAR",
    # PARLANTE
    "parlantes": "PARLANTE", "parlante": "PARLANTE",
    # PC
    "computadoras": "PC", "pc": "PC",
    # LAPTOP
    "laptops": "LAPTOP", "laptop": "LAPTOP",
    # TABLET
    "tablets": "TABLET", "tablet": "TABLET",
    # CELULAR
    "celulares": "CELULAR", "celular": "CELULAR",
    # SMARTWATCH
    "smartwatch": "SMARTWATCH",
    # VIDEOJUEGO
    "videojuegos": "VIDEOJUEGO", "videojuego": "VIDEOJUEGO",
    # TV
    "televisores": "TV", "tv": "TV",
    # IMPRESORA
    "impresoras": "IMPRESORA", "impresora": "IMPRESORA",
    # Core hardware
    "cooler": "COOLER",
    # Mayusculas (Newegg/eBay/Amazon)
    "CPU": "CPU",
    "GPU": "GPU",
    "RAM": "RAM",
    "SSD": "SSD",
    "MOTHERBOARD": "MOTHERBOARD",
    "PSU": "PSU",
    "CASE": "CASE",
    "COOLER": "COOLER",
    "HDD": "HDD",
    "LAPTOP": "LAPTOP",
    "MONITOR": "MONITOR",
    "MOUSE": "MOUSE",
    "KEYBOARD": "TECLADO",
    "AUDIO": "AURICULAR",
    "OTHER": "OTHER",
    "disco_duro_memorias": "HDD",
    "cpu": "CPU",
    "motherboard": "MOTHERBOARD",
    "psu": "PSU",
    "case": "CASE",
}

SOURCE_MAP = {
    # Falabella
    "falabella":            "falabella_pe",
    "falabella_pe":         "falabella_pe",
    "falabella_benchmark":  "falabella_pe",
    # Hiraoka
    "hiraoka":              "hiraoka_pe",
    "hiraoka_pe":           "hiraoka_pe",
    "hiraoka_benchmark":    "hiraoka_pe",
    # Internacionales
    "ebay_usa":             "ebay_usa",
    "amazon_usa":           "amazon_usa",
    "aliexpress":           "aliexpress",
    # Coolbox (por si aparece)
    "coolbox":              "coolbox_pe",
    "coolbox_pe":           "coolbox_pe",
    # Ripley (por si aparece)
    "ripley":               "ripley_pe",
    "ripley_pe":            "ripley_pe",
}

REQUIRED_COLUMNS = ["source", "category", "title", "price_pen", "price_usd", "price_date"]
COMPLETENESS_THRESHOLDS = {
    "price_usd":  75.0,
    "price_pen":  65.0,
    "price_date": 99.0,
    "source":    100.0,
    "title":      99.0,
    "category":   95.0,
    "sku":        75.0,
    "brand":      70.0,
}
PRICE_MAX_PEN = 50_000.0
PRICE_MAX_USD = 15_000.0

# ── [DQ1] Schema ───────────────────────────────────────────────────────────
def validate_schema(df):
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        print(f"\n FATAL [DQ1]: columnas obligatorias ausentes: {missing}")
        sys.exit(1)
    print(f"  [DQ1] OK Esquema OK - {len(REQUIRED_COLUMNS)} columnas obligatorias presentes")

# ── [DQ2] Completitud ──────────────────────────────────────────────────────
def validate_completeness(df):
    stats, warns = {}, []
    for col, thr in COMPLETENESS_THRESHOLDS.items():
        if col not in df.columns:
            continue
        pct = round((1 - df[col].isna().mean()) * 100, 2)
        stats[col] = pct
        if pct < thr:
            warns.append(f"    WARN {col}: {pct}% completo (minimo: {thr}%)")
    if warns:
        print(f"  [DQ2] WARN Completitud baja en {len(warns)} columna(s):")
        for w in warns:
            print(w)
    else:
        print(f"  [DQ2] OK Completitud OK en todas las columnas")
    return stats

# ── [DQ3] Outliers de precio ───────────────────────────────────────────────
def filter_price_outliers(df):
    n0 = len(df)
    df["price_pen"] = pd.to_numeric(df["price_pen"], errors="coerce")
    df["price_usd"] = pd.to_numeric(df["price_usd"], errors="coerce")
    mask = (
        df["price_pen"].isna() | df["price_usd"].isna() |
        (df["price_pen"] <= 0) | (df["price_usd"] <= 0) |
        (df["price_pen"] > PRICE_MAX_PEN) | (df["price_usd"] > PRICE_MAX_USD)
    )
    df = df[~mask].copy()
    print(f"  [DQ3] Outliers eliminados: {n0 - len(df):,} filas | "
          f"Rango PEN: S/{df['price_pen'].min():.2f} - S/{df['price_pen'].max():.2f}")
    return df

# ── [DQ4] Normalizar categorías ────────────────────────────────────────────
def normalize_categories(df):
    df = df.copy()
    b = df["category"].nunique()
    def _map_cat(x):
        if not isinstance(x, str):
            return "UNKNOWN"
        key = x.strip().lower()
        mapped = CATEGORY_MAP.get(key)
        if mapped:
            return mapped
        # Si ya está en mayúsculas y es conocida, la dejamos
        upper = x.strip().upper()
        if upper in {v for v in CATEGORY_MAP.values()}:
            return upper
        return "UNKNOWN"
    df["category"] = df["category"].map(_map_cat)
    n_unknown = (df["category"] == "UNKNOWN").sum()
    print(f"  [DQ4] Categorias: {b} -> {df['category'].nunique()} unicas "
          f"| UNKNOWN: {n_unknown:,} filas")
    print(f"         {df['category'].value_counts().to_dict()}")
    return df

# ── [DQ5] Normalizar fuentes ───────────────────────────────────────────────
def normalize_sources(df):
    df = df.copy()
    b = df["source"].nunique()
    df["source"] = df["source"].map(
        lambda x: SOURCE_MAP.get(x.strip().lower(), x) if isinstance(x, str) else x
    )
    print(f"  [DQ5] Fuentes: {b} -> {df['source'].nunique()} unicas")
    print(f"         {df['source'].value_counts().to_dict()}")
    return df

# ── [DQ6] Normalizar fechas ────────────────────────────────────────────────
def normalize_price_date(df):
    df = df.copy()
    parsed = pd.to_datetime(df["price_date"], errors="coerce")
    n_inv = int(parsed.isna().sum())
    if n_inv > 0:
        print(f"  [DQ6] WARN {n_inv:,} filas con price_date invalida -> eliminadas")
        df = df[parsed.notna()].copy()
        parsed = parsed[parsed.notna()]
    df["price_date"] = parsed.dt.strftime("%Y-%m-%d")
    print(f"  [DQ6] OK price_date ISO 8601 - "
          f"rango: {df['price_date'].min()} -> {df['price_date'].max()}")
    return df

# ── [DQ7] Deduplicar ──────────────────────────────────────────────────────
def deduplicate(df):
    n0 = len(df)
    if "fingerprint" in df.columns and df["fingerprint"].notna().sum() > 0:
        df = df.drop_duplicates(subset=["fingerprint"], keep="last")
        method = "fingerprint"
    else:
        keys = [c for c in ["source", "sku", "price_date", "price_usd"] if c in df.columns]
        df = df.drop_duplicates(subset=keys, keep="last")
        method = f"clave compuesta {keys}"
    print(f"  [DQ7] Duplicados: {n0 - len(df):,} eliminados ({method}) | "
          f"{n0:,} -> {len(df):,}")
    return df.reset_index(drop=True)

# ── [DQ8] Consolidar columnas duplicadas ──────────────────────────────────
def consolidate_columns(df):
    df = df.copy()
    changes = []

    # sold_qty + sold_quantity -> sold_qty
    if "sold_qty" in df.columns and "sold_quantity" in df.columns:
        df["sold_qty"] = df["sold_qty"].fillna(df["sold_quantity"])
        df.drop(columns=["sold_quantity"], inplace=True)
        changes.append("sold_quantity -> sold_qty")

    # reviews + reviews_count -> reviews
    if "reviews" in df.columns and "reviews_count" in df.columns:
        df["reviews"] = pd.to_numeric(df["reviews"], errors="coerce")
        df["reviews_count"] = pd.to_numeric(df["reviews_count"], errors="coerce")
        df["reviews"] = df["reviews"].fillna(df["reviews_count"])
        df.drop(columns=["reviews_count"], inplace=True)
        changes.append("reviews_count -> reviews")

    # shipping_free + free_shipping -> free_shipping
    if "shipping_free" in df.columns and "free_shipping" in df.columns:
        df["free_shipping"] = df["free_shipping"].fillna(df["shipping_free"])
        df.drop(columns=["shipping_free"], inplace=True)
        changes.append("shipping_free -> free_shipping")

    # scraped_at + timestamp -> timestamp (mantener timestamp)
    if "scraped_at" in df.columns and "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df["scraped_at"] = pd.to_datetime(df["scraped_at"], errors="coerce")
        df["timestamp"] = df["timestamp"].fillna(df["scraped_at"])
        df.drop(columns=["scraped_at"], inplace=True)
        changes.append("scraped_at -> timestamp")

    if changes:
        print(f"  [DQ8] Columnas consolidadas: {', '.join(changes)}")
    else:
        print(f"  [DQ8] OK Sin columnas duplicadas que consolidar")
    print(f"         Columnas finales: {df.shape[1]}")
    return df

# ── [DQ9] Reporte ─────────────────────────────────────────────────────────
def generate_report(df_before, df_after, completeness_stats, report_dir):
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report = {
        "batch_id": batch_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_step": "data_quality.py v1.1",
        "rows_before": int(len(df_before)),
        "rows_after": int(len(df_after)),
        "rows_removed": int(len(df_before) - len(df_after)),
        "pct_retained": round(len(df_after) / max(len(df_before), 1) * 100, 2),
        "completeness_pct": completeness_stats,
        "category_distribution": df_after["category"].value_counts().to_dict(),
        "source_distribution": df_after["source"].value_counts().to_dict(),
        "price_range": {
            "pen_min":    float(df_after["price_pen"].min()),
            "pen_max":    float(df_after["price_pen"].max()),
            "pen_median": float(df_after["price_pen"].median()),
            "usd_min":    float(df_after["price_usd"].min()),
            "usd_max":    float(df_after["price_usd"].max()),
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
    print(f"  [DQ9] OK Reporte guardado: {path.name}")
    return report

# ── Main ──────────────────────────────────────────────────────────────────
def run_data_quality(input_path, output_path, report_dir):
    report_dir.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("  DATA QUALITY v1.1 - Etapa I")
    print("=" * 60)

    df = pd.read_csv(input_path, low_memory=False)
    df_before = df.copy()
    print(f"\n MASTER cargado: {len(df):,} filas | {df.shape[1]} columnas")

    print("\n-- Validaciones --")
    validate_schema(df)
    completeness_stats = validate_completeness(df)

    print("\n-- Limpieza --")
    df = filter_price_outliers(df)
    df = normalize_categories(df)
    df = normalize_sources(df)
    df = normalize_price_date(df)
    df = deduplicate(df)
    df = consolidate_columns(df)

    n_rem = len(df_before) - len(df)
    print(f"\n-- Resultado final --")
    print(f"  Antes  : {len(df_before):,} | Despues: {len(df):,} | "
          f"Eliminadas: {n_rem:,} ({round(n_rem / len(df_before) * 100, 2)}%)")

    df.to_csv(output_path, index=False)
    print(f"\n OK MASTER limpio guardado: {output_path}")
    generate_report(df_before, df, completeness_stats, report_dir)

    print("\n" + "=" * 60)
    print("  OK data_quality.py v1.1 completado - listo para temporal_split.py")
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",      type=Path, default=Path("data/processed/MASTER_hardware_peru_clean.csv"))
    parser.add_argument("--output",     type=Path, default=Path("data/processed/MASTER_hardware_peru_clean.csv"))
    parser.add_argument("--report-dir", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    run_data_quality(args.input, args.output, args.report_dir)
