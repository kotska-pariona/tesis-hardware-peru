import numpy as np
import pandas as pd

# Carga matriz
path = "data/features/oe9_feature_matrix.csv"
df = pd.read_csv(path, encoding="utf-8")

# Reconstrucción USD (misma lógica usada en oe9_nsga3 v1.1 / v1.0 corregida)
roi = pd.to_numeric(df["roi_unitario_pct"], errors="coerce")
gan = pd.to_numeric(df["ganancia_unitaria"], errors="coerce")
rj  = pd.to_numeric(df["r_j"], errors="coerce")

valid = roi.notna() & gan.notna() & rj.notna()
dfv = df[valid].copy()

print("=== OE9 OBJECTIVE SMOKE TEST (USD) ===")
print("Valid SKUs:", len(dfv))

# Si no hay suficientes SKUs, salimos
if len(dfv) < 5:
    raise SystemExit("❌ No hay suficientes SKUs válidos para el test.")

# Parámetros del test
np.random.seed(42)
n_skus_test = min(10, len(dfv))
idx = np.random.choice(dfv.index.values, size=n_skus_test, replace=False)

# Unidades 1..5 para simular igual que NSGA-III
units = np.random.randint(1, 6, size=n_skus_test).astype(float)

# Construimos costos/ventas USD (consistente con roi y ganancia)
roi_frac = roi[valid] / 100.0
gan_v = gan[valid]
costo = gan_v.loc[idx].values / roi_frac.loc[idx].values
venta = costo + gan_v.loc[idx].values
rj_a  = rj.loc[idx].values

cats = pd.Categorical(dfv.loc[idx, "categoria"]).codes

# Cálculos portafolio
capital = float((costo * units).sum())
ingresos = float((venta * units).sum())
ganancia_total = float(ingresos - capital)
roi_port = (ganancia_total / capital * 100.0) if capital > 0 else 0.0

w = (costo * units) / capital if capital > 0 else np.ones_like(units) / len(units)
# f2: sqrt(varianza ponderada de ROI unitario)
rois_a = (roi.loc[idx].values.astype(float) / 100.0)
roi_mean = float((w * rois_a).sum())
f2 = float(np.sqrt((w * (rois_a - roi_mean) ** 2).sum()))

# f3: -n_cats
n_cats_act = len(np.unique(cats))
f3 = -float(n_cats_act)

# f4: HHI con pesos por ingresos
w_ingresos = (venta * units) / ingresos if ingresos > 0 else w
f4 = float((w_ingresos ** 2).sum())

# f5: rj promedio ponderado por capital
rj_port = float((w * rj_a).sum())
f5 = rj_port

print("\n--- Portafolio simulado ---")
print("SKUs seleccionados:", n_skus_test)
print("Unidades:", units.astype(int).tolist())
print(f"Capital (USD): {capital:,.2f}")
print(f"Ingresos (USD): {ingresos:,.2f}")
print(f"Ganancia (USD): {ganancia_total:,.2f}")
print(f"ROI portafolio (%): {roi_port:.2f}%")

print("\n--- Objetivos (según NSGA-III; todos minimizar) ---")
f1 = - (ganancia_total / capital) if capital > 0 else 0.0  # mismo que tu problema: f1=-roi_port_frac
# Nota: NSGA usa ROI frac (no %). Por eso f1 compara con roi_frac.
f1_check = - (ganancia_total / capital) if capital > 0 else 0.0
print("f1 (=-ROI frac) :", f1_check)
print("f2 (riesgo MC)  :", f2)
print("f3 (=-n_cats)   :", f3)
print("f4 (HHI)        :", f4)
print("f5 (rj_port)    :", f5)

# Restricciones (ejemplo)
BUDGET_USD = 50_000.0
RJ_MAX = 0.35
N_MIN_SKUS = 5

g1 = capital - BUDGET_USD
g2 = N_MIN_SKUS - n_skus_test
g3 = rj_port - RJ_MAX
print("\n--- Restricciones (g<=0 factible) ---")
print(f"g1 capital-budget: {g1:.2f}  -> {'OK' if g1<=0 else 'VIOLA'}")
print(f"g2 n_min-n_act   : {g2:.0f}  -> {'OK' if g2<=0 else 'VIOLA'}")
print(f"g3 rj_port-RJ_MAX : {g3:.4f}  -> {'OK' if g3<=0 else 'VIOLA'}")

print("\n--- Top detalle (primeros 5 SKUs del portafolio) ---")
tmp = dfv.loc[idx].copy()
tmp["unidades"] = units.astype(int)
tmp["costo_usd_impl"] = costo
tmp["venta_usd_impl"] = venta
tmp["ganancia_usd"] = venta - costo
tmp["roi_unitario_pct"] = roi.loc[idx].values
tmp["r_j"] = rj.loc[idx].values
tmp = tmp.sort_values("ganancia_usd", ascending=False).head(5)
cols = ["sku","producto","categoria","unidades","precio_import_usd","roi_unitario_pct","ganancia_usd","costo_usd_impl","venta_usd_impl","r_j"]
cols = [c for c in cols if c in tmp.columns]
print(tmp[cols].to_string(index=False))
