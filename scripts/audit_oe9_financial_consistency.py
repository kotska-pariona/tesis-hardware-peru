import pandas as pd
import numpy as np

path = "data/features/oe9_feature_matrix.csv"
df = pd.read_csv(path, encoding="utf-8")

roi = pd.to_numeric(df["roi_unitario_pct"], errors="coerce")
gan = pd.to_numeric(df["ganancia_unitaria"], errors="coerce")

print("=== FINANCIAL CONSISTENCY AUDIT (USD reconstruction) ===")
print("Total rows:", len(df))

valid = roi.notna() & gan.notna()
print("Valid rows (roi & ganancia notna):", int(valid.sum()))

roi_pos = (valid & (roi > 0))
roi_nonpos = (valid & (roi <= 0))
print("roi>0 count :", int(roi_pos.sum()))
print("roi<=0 count:", int(roi_nonpos.sum()))

roi_frac = roi / 100.0

# costo implícito según OE9 v1.1
costo_impl = np.where((roi_frac > 0) & valid, gan / roi_frac, np.nan)
venta_impl = costo_impl + gan

# stats
s_c = pd.Series(costo_impl).dropna()
s_v = pd.Series(venta_impl).dropna()

print("\n--- Impl. costo stats ---")
print(s_c.describe() if len(s_c) else "No hay costos válidos (NaN en reconstrucción).")

print("\n--- Impl. venta stats ---")
print(s_v.describe() if len(s_v) else "No hay ventas válidas (NaN en reconstrucción).")

# outliers por IQR
def outliers_iqr(x):
    if len(x) < 10:
        return x.iloc[0:0]
    q1, q3 = x.quantile(0.25), x.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return x.iloc[0:0]
    lo = q1 - 1.5 * iqr
    hi = q3 + 1.5 * iqr
    return x[(x < lo) | (x > hi)]

out_c = outliers_iqr(s_c)
out_v = outliers_iqr(s_v)

print("\nOutliers costo implícito (IQR):", len(out_c))
if len(out_c):
    print("Top 10 extremos costo:")
    idx = pd.Series(costo_impl).dropna().sort_values().head(5).index
    print(idx)

print("\nOutliers venta implícita (IQR):", len(out_v))

# muestra algunos ejemplos
show_n = 10
ex = df[valid].copy()
ex["roi_frac"] = roi_frac[valid].values
ex["costo_impl"] = costo_impl[valid]
ex["venta_impl"] = venta_impl[valid]
ex = ex.sort_values("roi_unitario_pct" if "roi_unitario_pct" in ex.columns else "roi_unitario_pct", ascending=False)
print("\n--- Ejemplos (primeros 10 por ROI unitario) ---")
cols_show = [c for c in ["sku","producto","categoria","roi_unitario_pct","ganancia_unitaria"] if c in ex.columns] + ["costo_impl","venta_impl"]
print(ex.head(show_n)[cols_show].to_string(index=False))
