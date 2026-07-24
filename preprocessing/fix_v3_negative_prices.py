"""
fix_v3_negative_prices.py
Etapa II.d — Eliminar día 12-julio corrupto y reconstruir splits
"""
import pandas as pd
import numpy as np
from pathlib import Path

FEATURES_DIR = Path("data/features")
TC_CORRECTO  = 3.70
BAD_DATE     = "2026-07-12"

print("=" * 60)
print("  FIX V3 — ELIMINACIÓN DÍA CORRUPTO 12-JUL")
print("=" * 60)

for split in ["train", "val", "test"]:
    df = pd.read_csv(FEATURES_DIR / f"{split}_features.csv", low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")

    n_orig   = len(df)
    mask_bad = df["price_date"].dt.strftime("%Y-%m-%d") == BAD_DATE
    n_bad    = mask_bad.sum()

    if n_bad > 0:
        df = df[~mask_bad].reset_index(drop=True)
        print(f"\n  [{split}] Eliminadas {n_bad} filas del {BAD_DATE}")
        print(f"  [{split}] {n_orig} → {len(df)} filas")
    else:
        print(f"\n  [{split}] Sin filas del {BAD_DATE}")

    # Recalcular features temporales limpias
    df = df.sort_values(["sku", "price_date"]).reset_index(drop=True)
    grp = df.groupby("sku")["price_usd"]

    df["price_usd_lag_1"]   = grp.shift(1)
    df["price_usd_ma_3"]    = grp.transform(lambda x: x.rolling(3, min_periods=1).mean())
    df["price_usd_ma_5"]    = grp.transform(lambda x: x.rolling(5, min_periods=1).mean())
    df["price_usd_std_3"]   = grp.transform(lambda x: x.rolling(3, min_periods=2).std())
    df["price_usd_std_5"]   = grp.transform(lambda x: x.rolling(5, min_periods=2).std())
    df["price_usd_pct_chg"] = grp.transform(lambda x: x.pct_change())

    cat_mean = df.groupby(["category","price_date"])["price_usd"].transform("mean")
    df["price_vs_cat_mean"] = (df["price_usd"] / cat_mean.replace(0, np.nan)).round(4)

    # Eliminar zscore (demasiados NaN)
    df.drop(columns=["price_usd_zscore"], inplace=True, errors="ignore")

    # Verificación
    neg   = (df["price_usd"] < 0).sum()
    over  = (df["price_usd"] > 15000).sum()
    print(f"  [{split}] price_usd < 0: {neg}  |  > 15k USD: {over}")
    print(f"  [{split}] shape final: {df.shape}")
    print(f"  [{split}] price_usd → mean={df['price_usd'].mean():.2f}  "
          f"min={df['price_usd'].min():.2f}  max={df['price_usd'].max():.2f}")

    df.to_csv(FEATURES_DIR / f"{split}_features.csv", index=False)

print()

# ── Reporte de fechas disponibles ─────────────────────────────────────────────
print("── Fechas disponibles por split ──")
for split in ["train", "val", "test"]:
    df = pd.read_csv(FEATURES_DIR / f"{split}_features.csv", low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"])
    fechas = sorted(df["price_date"].dt.date.unique())
    print(f"  [{split}] {len(fechas)} días: {fechas}")

print()
print("=" * 60)
print("  ✅ Fix v3 completado")
print("=" * 60)
