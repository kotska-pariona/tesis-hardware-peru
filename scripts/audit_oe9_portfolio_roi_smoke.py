import pandas as pd
import numpy as np

np.random.seed(42)
path = "data/features/oe9_feature_matrix.csv"
df = pd.read_csv(path, encoding="utf-8")

roi = pd.to_numeric(df["roi_unitario_pct"], errors="coerce")
gan = pd.to_numeric(df["ganancia_unitaria"], errors="coerce")
rj  = pd.to_numeric(df["r_j"], errors="coerce")

valid = roi.notna() & gan.notna() & rj.notna()
dfv = df[valid].copy()

roi = roi[valid]
gan = gan[valid]

print("=== PORTFOLIO ROI SMOKE TEST ===")
print("Valid SKUs:", len(dfv))

roi_frac = roi / 100.0
if len(dfv) == 0:
    print("❌ No hay SKUs válidos para reconstrucción.")
    raise SystemExit(1)

# reconstrucción USD
costo = gan / roi_frac
venta = costo + gan

dfv["costo_usd_impl"] = costo.values
dfv["venta_usd_impl"] = venta.values

n_tests = 50
min_skus = 5
max_skus = min(20, len(dfv))

roi_list = []
rj_list = []

for _ in range(n_tests):
    n = np.random.randint(min_skus, max_skus + 1)
    idx = np.random.choice(dfv.index.values, size=n, replace=False)

    costos_a = dfv.loc[idx, "costo_usd_impl"].values
    ventas_a = dfv.loc[idx, "venta_usd_impl"].values
    rj_a = dfv.loc[idx, "r_j"].values

    capital = (costos_a * 1).sum()  # OJO: unidades = 1 por SKU en este smoke (robusto)
    ingresos = (ventas_a * 1).sum()
    ganancia = ingresos - capital
    roi_pct = ganancia / capital * 100 if capital > 0 else 0.0

    w = (costos_a * 1) / capital if capital > 0 else np.ones(n) / n
    rj_port = float((w * rj_a).sum())

    roi_list.append(roi_pct)
    rj_list.append(rj_port)

roi_arr = np.array(roi_list, dtype=float)
rj_arr = np.array(rj_list, dtype=float)

print("Tests:", n_tests)
print("ROI% stats:", np.nanmin(roi_arr), "to", np.nanmax(roi_arr),
      "| mean:", np.nanmean(roi_arr), "| median:", np.nanmedian(roi_arr))
print("rj stats:", np.nanmin(rj_arr), "to", np.nanmax(rj_arr),
      "| mean:", np.nanmean(rj_arr), "| median:", np.nanmedian(rj_arr))
print("Count ROI<0:", int((roi_arr < 0).sum()))
print("ROI% samples:", np.round(roi_arr[:15], 2))
