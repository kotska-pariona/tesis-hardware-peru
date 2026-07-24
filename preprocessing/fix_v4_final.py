"""
fix_v4_final.py  — THE FINAL FIX
Fuente: data/processed/*_features.csv  (originales con día 12)
Salida: data/features/*_features.csv   (limpios y consistentes)

Acciones:
  1. Corregir price_usd con TC=3.70 donde sea incorrecto (negativos o >15k con price_pen razonable)
  2. Eliminar columnas 100% NaN
  3. Recalcular features temporales sobre dataset COMPLETO (sin leakage)
  4. Re-splitear con columnas consistentes
"""
import pandas as pd
import numpy as np
from pathlib import Path

SRC_DIR  = Path("data/processed")
OUT_DIR  = Path("data/features")
TC       = 3.70
SPLITS   = ["train", "val", "test"]

print("=" * 60)
print("  FIX V4 FINAL — DESDE ORIGINALES")
print("=" * 60)

# ── 1. Cargar originales y unir ───────────────────────────────
dfs = []
for s in SPLITS:
    df = pd.read_csv(SRC_DIR / f"{s}_features.csv", low_memory=False)
    df["_split"] = s
    print(f"\n  [{s}] cargado: {df.shape}")
    dfs.append(df)

# Alinear columnas
all_cols = sorted(set().union(*[set(d.columns) for d in dfs]))
for i, df in enumerate(dfs):
    for col in all_cols:
        if col not in df.columns:
            dfs[i][col] = np.nan

full = pd.concat(dfs, ignore_index=True)
print(f"\n✅ Dataset unificado: {full.shape}")

# ── 2. Corregir price_usd ─────────────────────────────────────
full["price_date"] = pd.to_datetime(full["price_date"], errors="coerce")

# Caso A: negativos → siempre recalcular desde price_pen
mask_neg = full["price_usd"] < 0
# Caso B: >15k USD pero price_pen/TC <= 15k → error de TC
mask_tc  = (full["price_usd"] > 15000) & (full["price_pen"] / TC <= 15000)

n_neg = mask_neg.sum()
n_tc  = mask_tc.sum()
print(f"\n  Corrigiendo {n_neg} negativos + {n_tc} errores TC...")

full.loc[mask_neg | mask_tc, "price_usd"] = (
    full.loc[mask_neg | mask_tc, "price_pen"] / TC
).round(4)

# Verificar
still_neg = (full["price_usd"] < 0).sum()
print(f"  Negativos restantes: {still_neg}")
print(f"  price_usd → mean={full['price_usd'].mean():.2f}  "
      f"min={full['price_usd'].min():.2f}  "
      f"max={full['price_usd'].max():.2f}")

# ── 3. Eliminar columnas 100% NaN ─────────────────────────────
dead = [c for c in full.columns
        if c != "_split" and full[c].isna().mean() == 1.0]
full.drop(columns=dead, inplace=True)
print(f"\n  Eliminadas {len(dead)} columnas 100% NaN")

# ── 4. Limpiar features temporales viejas ────────────────────
old = [c for c in full.columns if any(c.startswith(p) for p in
       ["price_usd_lag","price_usd_ma","price_usd_std",
        "price_usd_pct","price_usd_zscore","price_vs_cat"])]
full.drop(columns=old, inplace=True, errors="ignore")

# ── 5. Recalcular features temporales sobre full ─────────────
print("\n🔧 Recalculando features temporales...")
full = full.sort_values(["sku","price_date"]).reset_index(drop=True)
grp  = full.groupby("sku")["price_usd"]

full["price_usd_lag_1"]   = grp.shift(1)
full["price_usd_ma_3"]    = grp.transform(lambda x: x.rolling(3, min_periods=1).mean())
full["price_usd_ma_5"]    = grp.transform(lambda x: x.rolling(5, min_periods=1).mean())
full["price_usd_std_3"]   = grp.transform(lambda x: x.rolling(3, min_periods=2).std())
full["price_usd_std_5"]   = grp.transform(lambda x: x.rolling(5, min_periods=2).std())
full["price_usd_pct_chg"] = grp.transform(lambda x: x.pct_change())

cat_mean = full.groupby(["category","price_date"])["price_usd"].transform("mean")
full["price_vs_cat_mean"] = (full["price_usd"] / cat_mean.replace(0, np.nan)).round(4)

print("  ✅ Features recalculadas")

# ── 6. Re-splitear y guardar ──────────────────────────────────
print("\n💾 Guardando splits...")
final_cols = [c for c in full.columns if c != "_split"]

temp_check = ["price_usd_lag_1","price_usd_ma_3","price_usd_ma_5",
              "price_usd_std_3","price_usd_pct_chg","price_vs_cat_mean"]

for s in SPLITS:
    df_s = full[full["_split"] == s][final_cols].reset_index(drop=True)
    df_s.to_csv(OUT_DIR / f"{s}_features.csv", index=False)

    neg  = (df_s["price_usd"] < 0).sum()
    fechas = sorted(df_s["price_date"].dt.date.unique())
    print(f"\n  [{s}] shape={df_s.shape}  negativos={neg}  días={len(fechas)}")
    print(f"  [{s}] fechas: {fechas}")
    print(f"  [{s}] mean={df_s['price_usd'].mean():.2f}  "
          f"min={df_s['price_usd'].min():.2f}  "
          f"max={df_s['price_usd'].max():.2f}")
    for col in temp_check:
        if col in df_s.columns:
            nan_pct = df_s[col].isna().mean() * 100
            st = "✅" if nan_pct < 15 else "⚠️" if nan_pct < 50 else "❌"
            print(f"    {st} {col:<25} NaN: {nan_pct:.1f}%")

print()
print("=" * 60)
print("  ✅ FIX V4 COMPLETADO — dataset limpio y consistente")
print("=" * 60)
