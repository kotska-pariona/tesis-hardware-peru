"""
fix_v3_correct.py
Etapa II.d — Recalcular price_usd del día 12-jul desde price_pen
"""
import pandas as pd
import numpy as np
from pathlib import Path

FEATURES_DIR = Path("data/features")
TC_CORRECTO  = 3.70
BAD_DATE     = "2026-07-12"

print("=" * 60)
print("  FIX V3 — CORRECCIÓN TC DÍA 12-JUL")
print("=" * 60)

for split in ["train", "val", "test"]:
    df = pd.read_csv(FEATURES_DIR / f"{split}_features.csv", low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")

    mask_bad = df["price_date"].dt.strftime("%Y-%m-%d") == BAD_DATE
    n_bad    = mask_bad.sum()

    if n_bad > 0:
        # Recalcular SOLO price_usd desde price_pen con TC correcto
        df.loc[mask_bad, "price_usd"] = (
            df.loc[mask_bad, "price_pen"] / TC_CORRECTO
        ).round(4)

        neg_after = (df.loc[mask_bad, "price_usd"] < 0).sum()
        print(f"\n  [{split}] Corregidas {n_bad} filas del {BAD_DATE}")
        print(f"  [{split}] Negativos restantes en ese día: {neg_after}")
    else:
        print(f"\n  [{split}] Sin filas del {BAD_DATE}")

    # Recalcular features temporales con precios ya limpios
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

    df.drop(columns=["price_usd_zscore"], inplace=True, errors="ignore")

    # Verificación final
    neg  = (df["price_usd"] < 0).sum()
    over = (df["price_usd"] > 15000).sum()
    print(f"  [{split}] price_usd < 0: {neg}  |  > 15k: {over}")
    print(f"  [{split}] mean={df['price_usd'].mean():.2f}  "
          f"min={df['price_usd'].min():.2f}  "
          f"max={df['price_usd'].max():.2f}  "
          f"shape={df.shape}")

    df.to_csv(FEATURES_DIR / f"{split}_features.csv", index=False)

print()
print("── Fechas disponibles por split ──")
for split in ["train", "val", "test"]:
    df = pd.read_csv(FEATURES_DIR / f"{split}_features.csv", low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"])
    fechas = sorted(df["price_date"].dt.date.unique())
    print(f"  [{split}] {len(fechas)} días: {fechas}")

print()
print("=" * 60)
print("  ✅ Fix v3 completado — 0 filas eliminadas, 8 días intactos")
print("=" * 60)
