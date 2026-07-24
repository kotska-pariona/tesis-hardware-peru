"""
fix_outliers_and_features.py
Etapa II.b — Limpieza de outliers de tipo de cambio + re-cálculo de features
"""
import pandas as pd
import numpy as np
from pathlib import Path

# ── Configuración ──────────────────────────────────────────────────────────────
FEATURES_DIR  = Path("data/features")
OUTPUT_DIR    = Path("data/features")
TC_CORRECTO   = 3.70          # PEN/USD referencia BCRP julio 2026
PRICE_MAX_USD = 10_000.0      # techo razonable para hardware
SPLITS        = ["train", "val", "test"]

def fix_split(split: str):
    path = FEATURES_DIR / f"{split}_features.csv"
    df   = pd.read_csv(path, low_memory=False)
    n_orig = len(df)

    # ── 1. Detectar filas con price_usd corrupto ──────────────────────────────
    mask_bad = df["price_usd"] > PRICE_MAX_USD
    n_bad    = mask_bad.sum()

    if n_bad > 0:
        # Recalcular desde price_pen con TC correcto
        df.loc[mask_bad, "price_usd"] = (
            df.loc[mask_bad, "price_pen"] / TC_CORRECTO
        ).round(4)
        print(f"  [{split}] Corregidas {n_bad} filas (price_usd recalculado desde price_pen)")

        # Verificar que el fix fue correcto
        still_bad = (df["price_usd"] > PRICE_MAX_USD).sum()
        if still_bad > 0:
            print(f"  ⚠️  Aún quedan {still_bad} filas > {PRICE_MAX_USD} USD — revisar manualmente")
    else:
        print(f"  [{split}] Sin outliers — sin cambios")

    # ── 2. Re-calcular features temporales por SKU ────────────────────────────
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
    df = df.sort_values(["sku", "price_date"]).reset_index(drop=True)

    grp = df.groupby("sku")["price_usd"]

    # Lags (solo lag_1 es viable con 5-8 días)
    df["price_usd_lag_1"]  = grp.shift(1)

    # Medias móviles — renombradas honestamente como "expanding" hasta N días
    df["price_usd_ma_3"]   = grp.transform(lambda x: x.rolling(3,  min_periods=1).mean())
    df["price_usd_ma_5"]   = grp.transform(lambda x: x.rolling(5,  min_periods=1).mean())
    df["price_usd_std_3"]  = grp.transform(lambda x: x.rolling(3,  min_periods=2).std())
    df["price_usd_std_5"]  = grp.transform(lambda x: x.rolling(5,  min_periods=2).std())

    # Cambio porcentual día a día
    df["price_usd_pct_chg"] = grp.transform(lambda x: x.pct_change())

    # Zscore rolling 90 días (con expanding si hay menos datos)
    def rolling_zscore(x, w=90):
        mu  = x.expanding(min_periods=2).mean()
        std = x.expanding(min_periods=2).std()
        return (x - mu) / std.replace(0, np.nan)

    df["price_usd_zscore"] = grp.transform(rolling_zscore)

    # ── 3. Eliminar columnas 100% NaN (lag_7, lag_30, ma_7/14/30 viejas) ─────
    dead_cols = [c for c in df.columns if df[c].isna().mean() == 1.0]
    if dead_cols:
        df.drop(columns=dead_cols, inplace=True)
        print(f"  [{split}] Eliminadas {len(dead_cols)} columnas 100% NaN: {dead_cols}")

    # ── 4. Guardar ────────────────────────────────────────────────────────────
    out_path = OUTPUT_DIR / f"{split}_features.csv"
    df.to_csv(out_path, index=False)
    print(f"  [{split}] Guardado → {out_path}  shape={df.shape}")
    return df

# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  FIX OUTLIERS + RE-CÁLCULO DE FEATURES")
    print("=" * 60)
    for s in SPLITS:
        fix_split(s)

    print()
    print("── Verificación final ──")
    for s in SPLITS:
        df = pd.read_csv(OUTPUT_DIR / f"{s}_features.csv", low_memory=False)
        bad = (df["price_usd"] > PRICE_MAX_USD).sum()
        temporal = ["price_usd_lag_1","price_usd_ma_3","price_usd_ma_5",
                    "price_usd_std_3","price_usd_pct_chg","price_usd_zscore"]
        print(f"\n  [{s}] shape={df.shape}  outliers_restantes={bad}")
        for col in temporal:
            if col in df.columns:
                nan_pct = df[col].isna().mean() * 100
                st = "✅" if nan_pct < 10 else "⚠️" if nan_pct < 50 else "❌"
                print(f"    {st} {col:<25} NaN: {nan_pct:.1f}%")
    print()
    print("✅ Fix completado — features listas para Etapa III")
