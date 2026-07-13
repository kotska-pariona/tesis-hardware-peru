#!/usr/bin/env python3
"""
migrate_master.py v1.0
========================================================================
Migracion RETROACTIVA de MASTER_hardware_peru.csv existente (40,040 filas)
aplicando la misma logica de normalize_schema() + convert_currency() que
main.py v5.9 aplica hacia adelante.

NO SOBRESCRIBE el original. Genera:
  - data/raw/MASTER_hardware_peru_v2.csv   (dataset migrado)
  - data/raw/MASTER_exchange_rate.csv       (filas exchangerate_api separadas)
  - data/raw/migration_report.json          (resumen de cambios)

Uso:
  python migrate_master.py
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path("data/raw")
SRC_PATH = DATA_DIR / "MASTER_hardware_peru.csv"
DST_PATH = DATA_DIR / "MASTER_hardware_peru_v2.csv"
EXCH_PATH = DATA_DIR / "MASTER_exchange_rate.csv"
REPORT_PATH = DATA_DIR / "migration_report.json"

# Rate confirmado por diagnostico: promedio de las 2 filas exchangerate_api
# (3.4024 del 10-jul y 3.3962 del 11-jul). Rango de datos es solo 2 dias,
# por eso un rate unico es representativo -- no se requiere date-matching.
RATE_MID = round((3.4024 + 3.3962) / 2, 4)

ALIAS_GROUPS = {
    "sku":            ["sku", "asin_sku", "item_id", "part_id"],
    "available_qty":  ["available_qty", "available"],
    "price_orig_pen": ["price_orig_pen", "original_price"],
    "free_shipping":  ["free_shipping", "shipping_free"],
    "price_currency": ["price_currency", "currency"],
}


def normalize_schema_df(df: pd.DataFrame) -> pd.DataFrame:
    """Version vectorizada de normalize_schema() para migracion retroactiva."""
    for canon, aliases in ALIAS_GROUPS.items():
        if canon not in df.columns:
            df[canon] = np.nan
        for alt in aliases[1:]:
            if alt in df.columns:
                df[canon] = df[canon].where(
                    df[canon].notna() & (df[canon] != ""), df[alt]
                )

    # price_date derivado de timestamp cuando falte
    if "price_date" not in df.columns:
        df["price_date"] = np.nan
    ts_as_date = pd.to_datetime(df["timestamp"], errors="coerce", utc=True).dt.strftime("%Y-%m-%d")
    mask_empty_pd = df["price_date"].isna() | (df["price_date"] == "")
    df.loc[mask_empty_pd, "price_date"] = ts_as_date[mask_empty_pd]

    return df


def convert_currency_df(df: pd.DataFrame, rate_mid: float) -> pd.DataFrame:
    """Version vectorizada de convert_currency() para migracion retroactiva."""
    usd = pd.to_numeric(df.get("price_usd"), errors="coerce")
    pen = pd.to_numeric(df.get("price_pen"), errors="coerce")

    fill_usd_mask = usd.isna() & pen.notna()
    fill_pen_mask = pen.isna() & usd.notna()

    n_usd_filled = int(fill_usd_mask.sum())
    n_pen_filled = int(fill_pen_mask.sum())

    df.loc[fill_usd_mask, "price_usd"] = (pen[fill_usd_mask] / rate_mid).round(2)
    df.loc[fill_pen_mask, "price_pen"] = (usd[fill_pen_mask] * rate_mid).round(2)

    return df, n_usd_filled, n_pen_filled


def main():
    print(f"Cargando {SRC_PATH} ...")
    df = pd.read_csv(SRC_PATH, low_memory=False)
    total_before = len(df)
    print(f"  {total_before:,} filas cargadas")

    # ---- Metricas ANTES (para el reporte) ----
    def pct_complete(col):
        if col not in df.columns:
            return 0.0
        return round(100 * df[col].notna().sum() / len(df), 2)

    before = {
        "price_usd":   pct_complete("price_usd"),
        "price_date":  pct_complete("price_date"),
        "sku":         pct_complete("sku"),
        "available_qty": pct_complete("available_qty"),
    }

    # ---- 1. Separar filas de tipo de cambio ----
    is_exchange = df["source"] == "exchangerate_api"
    exch_rows = df[is_exchange].copy()
    df = df[~is_exchange].copy()
    print(f"  Separadas {len(exch_rows)} filas de exchangerate_api -> MASTER_exchange_rate.csv")

    if not exch_rows.empty:
        ts_as_date = pd.to_datetime(exch_rows["timestamp"], errors="coerce", utc=True).dt.strftime("%Y-%m-%d")
        exch_rows["date"] = ts_as_date  # fix bug [D13]: date truncada -> derivada de timestamp
        exch_rows.to_csv(EXCH_PATH, index=False)

    # ---- 2. normalize_schema (vectorizado) ----
    print("Aplicando normalize_schema()...")
    df = normalize_schema_df(df)

    # ---- 3. convert_currency (vectorizado) ----
    print(f"Aplicando convert_currency() con rate_mid={RATE_MID}...")
    df, n_usd_filled, n_pen_filled = convert_currency_df(df, RATE_MID)

    # ---- Metricas DESPUES ----
    after = {
        "price_usd":   pct_complete("price_usd"),
        "price_date":  pct_complete("price_date"),
        "sku":         pct_complete("sku"),
        "available_qty": pct_complete("available_qty"),
    }

    # ---- 4. Guardar resultado ----
    df.to_csv(DST_PATH, index=False)
    print(f"Guardado: {DST_PATH} ({len(df):,} filas)")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rate_mid_used": RATE_MID,
        "rows_before": total_before,
        "rows_after_product_master": len(df),
        "rows_moved_to_exchange_rate": len(exch_rows),
        "price_usd_filled_by_conversion": n_usd_filled,
        "price_pen_filled_by_conversion": n_pen_filled,
        "completeness_pct_before": before,
        "completeness_pct_after": after,
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print("RESUMEN DE MIGRACION")
    print("=" * 60)
    for k in before:
        print(f"  {k:<16} {before[k]:>6.2f}%  ->  {after[k]:>6.2f}%")
    print(f"  price_usd rellenados por conversion: {n_usd_filled:,}")
    print(f"  price_pen rellenados por conversion: {n_pen_filled:,}")
    print("=" * 60)
    print(f"Reporte completo: {REPORT_PATH}")


if __name__ == "__main__":
    main()
