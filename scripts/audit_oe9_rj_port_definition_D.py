import numpy as np
import pandas as pd

"""
Objetivo:
1) Determinar cómo se calcula r_j_port en la lógica que usas para el portafolio.
2) Lo hacemos replicando 3 variantes comunes y reportando cuál coincide mejor
   con el "r_j_port" que tu smoke test/NSGA suele producir.

Como aquí no tenemos acceso directo a tu clase NSGA-III, generamos:
- un portafolio de prueba con un capital objetivo ingresado por usuario
- calculamos r_j_port bajo:
  (1) ponderación por capital (w ~ costo*units)
  (2) ponderación por ingresos (w ~ venta*units)
  (3) ponderación uniforme

Salida:
- imprime las 3 versiones y su relación con el RJ_MAX configurado
- y además muestra qué categorías tienden a romper la restricción.
"""

# ====== CONFIGURACIÓN (ajusta si quieres) ======
path = "data/features/oe9_feature_matrix.csv"
RJ_MAX = 0.35
np.random.seed(42)

# capital objetivo "ingresado por el usuario"
# (cámbialo aquí si prefieres; si quieres interactivo lo dejo para otro script)
CAPITAL_TARGET_USD = 5000.0

# número de SKUs en el portafolio de prueba
N_SKUS_TEST = 10

# ==============================================
df = pd.read_csv(path, encoding="utf-8")

# parse numéricas
for c in ["roi_unitario_pct", "ganancia_unitaria", "r_j"]:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

valid = df["roi_unitario_pct"].notna() & df["ganancia_unitaria"].notna() & df["r_j"].notna()
dfv = df[valid].copy()

print("=== D) Verificar definición de r_j_port (capital vs ingresos vs uniforme) ===")
print("Capital objetivo (USD):", CAPITAL_TARGET_USD)
print("RJ_MAX:", RJ_MAX)
print("Valid SKUs:", len(dfv))
print("N_SKUS_TEST:", N_SKUS_TEST)

if len(dfv) < N_SKUS_TEST:
    raise SystemExit("❌ No hay suficientes SKUs válidos para el test.")

# seleccionar SKUs de prueba
idx = np.random.choice(dfv.index.values, size=N_SKUS_TEST, replace=False)
sub = dfv.loc[idx].copy()

# reconstrucción USD costo/venta usando roi_unitario_pct y ganancia_unitaria
roi_frac = sub["roi_unitario_pct"].values / 100.0
gan = sub["ganancia_unitaria"].values
costo = gan / roi_frac
venta = costo + gan
rj = sub["r_j"].values

cats = sub["categoria"].astype(str).values if "categoria" in sub.columns else np.array(["NA"]*len(sub))

# ====== Generar unidades para que el capital sea ~CAPITAL_TARGET_USD ======
# En tu idea: el usuario ingresa capital y el agente calcula cantidades.
# Aquí lo simplificamos: asignamos unidades enteras proporcionales a "costo"
# (esto NO reproduce exactamente tu agente, pero sirve para comparar definiciones de r_j_port).
raw = np.array([max(1, int(round((CAPITAL_TARGET_USD / costo_i) / N_SKUS_TEST))) for costo_i in costo], dtype=int)
# Ajuste para aproximar mejor el capital total
capital_actual = float((costo * raw).sum())

# mini-ajuste: escalamos uniformemente si está muy lejos
scale = CAPITAL_TARGET_USD / capital_actual if capital_actual > 0 else 1.0
units = np.maximum(1, np.floor(raw * scale).astype(int))
# recalcular capital
capital_actual = float((costo * units).sum())

ingresos_actual = float((venta * units).sum())

print("\n--- Portafolio de prueba ---")
print("SKUs:", N_SKUS_TEST)
print("Units (enteras):", units.tolist())
print(f"Capital actual (USD): {capital_actual:,.2f}")
print(f"Ingresos actual (USD): {ingresos_actual:,.2f}")

# ====== Tres versiones de r_j_port ======
# (1) ponderación por capital
w_cap = (costo * units) / capital_actual if capital_actual > 0 else np.ones_like(units)/len(units)
rj_port_cap = float((w_cap * rj).sum())

# (2) ponderación por ingresos
w_ing = (venta * units) / ingresos_actual if ingresos_actual > 0 else np.ones_like(units)/len(units)
rj_port_ing = float((w_ing * rj).sum())

# (3) uniforme
rj_port_uni = float(rj.mean())

print("\n--- r_j_port bajo 3 esquemas (todos minimizan; restricción r_j_port<=RJ_MAX) ---")
print(f"1) Ponderado por CAPITAL : rj_port = {rj_port_cap:.6f} -> {'OK' if rj_port_cap<=RJ_MAX else 'VIOLA'}")
print(f"2) Ponderado por INGRESOS: rj_port = {rj_port_ing:.6f} -> {'OK' if rj_port_ing<=RJ_MAX else 'VIOLA'}")
print(f"3) PESO UNIFORME        : rj_port = {rj_port_uni:.6f} -> {'OK' if rj_port_uni<=RJ_MAX else 'VIOLA'}")

# Mostrar desglose por categoría
if "categoria" in sub.columns:
    tmp = sub[["sku","categoria","roi_unitario_pct","ganancia_unitaria","r_j"]].copy() if "sku" in sub.columns else sub.copy()
    tmp["unidades"] = units.astype(int)
    tmp["costo_usd_impl"] = costo
    tmp["venta_usd_impl"] = venta
    # contribución de pesos
    tmp["w_cap"] = w_cap
    tmp["w_ing"] = w_ing
    tmp = tmp.sort_values("r_j", ascending=False)
    cols_show = [c for c in ["sku","categoria","unidades","r_j","w_cap","w_ing"] if c in tmp.columns]
    print("\n--- Top por r_j (para ver qué está empujando la restricción) ---")
    print(tmp.head(10)[cols_show].to_string(index=False))

print("\nSiguiente paso:")
print("- Si tú ya tienes un r_j_port reportado por tu NSGA-III, compáralo contra estas 3 cifras.")
print("- La que coincida (o esté más cerca) indica la ponderación correcta.")
