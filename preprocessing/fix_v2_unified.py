"""
fix_v2_unified.py
Etapa II.c — Fix unificado:
  1. Inspecciona outliers restantes > 10k USD
  2. Calcula features temporales sobre dataset COMPLETO (sin data leakage)
  3. Re-splitea con columnas consistentes
"""
import pandas as pd
import numpy as np
from pathlib import Path

FEATURES_DIR = Path("data/features")
OUTPUT_DIR   = Path("data/features")
TC_CORRECTO  = 3.70
PRICE_MAX    = 10_000.0

# ── 1. Cargar los 3 splits y unir ─────────────────────────────────────────────
print("=" * 60)
print("  FIX V2 — UNIFICADO")
print("=" * 60)

splits = {}
for s in ["train", "val", "test"]:
    df = pd.read_csv(FEATURES_DIR / f"{s}_features.csv", low_memory=False)
    df["_split"] = s
    splits[s] = df

# Alinear columnas — usar unión de todas
all_cols = sorted(set().union(*[set(df.columns) for df in splits.values()]))
for s in splits:
    for col in all_cols:
        if col not in splits[s].columns:
            splits[s][col] = np.nan

full = pd.concat([splits["train"], splits["val"], splits["test"]], ignore_index=True)
print(f"\n✅ Dataset unificado: {full.shape}")

# ── 2. Inspeccionar outliers restantes ────────────────────────────────────────
bad = full[full["price_usd"] > PRICE_MAX][["_split","sku","price_date",
                                            "price_usd","price_pen","category"]].copy()
bad["ratio"] = (bad["price_usd"] / (bad["price_pen"] / TC_CORRECTO)).round(2)
print(f"\n⚠️  Filas aún > ${PRICE_MAX:,.0f} USD: {len(bad)}")
print(bad.sort_values("price_usd", ascending=False).head(20).to_string())

# Decisión: si price_pen existe y es razonable → recalcular
# Si price_pen también es enorme → es producto legítimo (servidor/workstation)
mask_recalc = (full["price_usd"] > PRICE_MAX) & (full["price_pen"] / TC_CORRECTO <= PRICE_MAX)
mask_legit  = (full["price_usd"] > PRICE_MAX) & (full["price_pen"] / TC_CORRECTO >  PRICE_MAX)

print(f"\n  → Recalculables (TC error):  {mask_recalc.sum()}")
print(f"  → Legítimos (precio real):   {mask_legit.sum()}")

full.loc[mask_recalc, "price_usd"] = (
    full.loc[mask_recalc, "price_pen"] / TC_CORRECTO
).round(4)

# ── 3. Recalcular features temporales sobre dataset COMPLETO ──────────────────
print("\n🔧 Recalculando features temporales (sin data leakage)...")

full["price_date"] = pd.to_datetime(full["price_date"], errors="coerce")
full = full.sort_values(["sku", "price_date"]).reset_index(drop=True)

# Eliminar features temporales viejas para recalcular limpias
old_temp = [c for c in full.columns if any(c.startswith(p) for p in
            ["price_usd_lag","price_usd_ma","price_usd_std",
             "price_usd_pct","price_usd_zscore"])]
full.drop(columns=old_temp, inplace=True, errors="ignore")

grp = full.groupby("sku")["price_usd"]

# Lag 1 — precio del día anterior del mismo SKU
full["price_usd_lag_1"]   = grp.shift(1)

# Medias móviles (min_periods=1 para no perder filas)
full["price_usd_ma_3"]    = grp.transform(lambda x: x.rolling(3, min_periods=1).mean())
full["price_usd_ma_5"]    = grp.transform(lambda x: x.rolling(5, min_periods=1).mean())

# Desviación estándar (min_periods=2)
full["price_usd_std_3"]   = grp.transform(lambda x: x.rolling(3, min_periods=2).std())
full["price_usd_std_5"]   = grp.transform(lambda x: x.rolling(5, min_periods=2).std())

# Cambio porcentual
full["price_usd_pct_chg"] = grp.transform(lambda x: x.pct_change())

# Zscore expanding
def expanding_zscore(x):
    mu  = x.expanding(min_periods=2).mean()
    std = x.expanding(min_periods=2).std()
    return (x - mu) / std.replace(0, np.nan)

full["price_usd_zscore"]  = grp.transform(expanding_zscore)

# Precio relativo al promedio de categoría (feature cross-seccional)
cat_mean = full.groupby(["category","price_date"])["price_usd"].transform("mean")
full["price_vs_cat_mean"] = (full["price_usd"] / cat_mean.replace(0, np.nan)).round(4)

print("  ✅ Features recalculadas")

# ── 4. Re-splitear con columnas consistentes ──────────────────────────────────
print("\n💾 Guardando splits con columnas consistentes...")

final_cols = [c for c in full.columns if c != "_split"]

for s in ["train", "val", "test"]:
    df_s = full[full["_split"] == s][final_cols].reset_index(drop=True)
    out  = OUTPUT_DIR / f"{s}_features.csv"
    df_s.to_csv(out, index=False)

    # Reporte
    temp_cols = ["price_usd_lag_1","price_usd_ma_3","price_usd_ma_5",
                 "price_usd_std_3","price_usd_pct_chg","price_usd_zscore",
                 "price_vs_cat_mean"]
    bad_count = (df_s["price_usd"] > PRICE_MAX).sum()
    print(f"\n  [{s}] shape={df_s.shape}  outliers={bad_count}")
    for col in temp_cols:
        if col in df_s.columns:
            nan_pct = df_s[col].isna().mean() * 100
            st = "✅" if nan_pct < 15 else "⚠️" if nan_pct < 50 else "❌"
            print(f"    {st} {col:<25} NaN: {nan_pct:.1f}%")

print("\n" + "=" * 60)
print("  ✅ Etapa II.c completada — features consistentes y limpias")
print("=" * 60)
