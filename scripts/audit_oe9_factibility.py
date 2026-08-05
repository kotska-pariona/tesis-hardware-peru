import json
import pandas as pd

path_json = "results/oe9_resumen_nsga3.json"
path_csv  = "results/oe9_pareto_front.csv"

with open(path_json,"r",encoding="utf-8") as f:
    j=json.load(f)

# rj_max viene del resumen
rj_max = j.get("rj_max", None)
if rj_max is None:
    # algunos logs pueden usar otra clave
    rj_max = j.get("RJ_MAX", None)
if rj_max is None:
    raise SystemExit("No se encontró rj_max en oe9_resumen_nsga3.json")

df=pd.read_csv(path_csv)

if "rj_portafolio" not in df.columns:
    raise SystemExit("No existe columna rj_portafolio en oe9_pareto_front.csv")

df["factible_rj"] = df["rj_portafolio"] <= float(rj_max)

total = len(df)
n_fact = int(df["factible_rj"].sum())
n_viol = total - n_fact

print("=== OE9 Factibilidad por RJ ===")
print("rj_max:", rj_max)
print("Total soluciones pareto:", total)
print("Factibles (rj_portafolio <= rj_max):", n_fact, f"({n_fact/total*100:.1f}%)")
print("Violación (rj_portafolio > rj_max):", n_viol, f"({n_viol/total*100:.1f}%)")

# Resumen numérico de los rj_portafolio
s = pd.to_numeric(df["rj_portafolio"], errors="coerce")
print("\nStats rj_portafolio:")
print(s.describe().to_string())

# Cuánto se pasa cuando viola
viol = df.loc[~df["factible_rj"]].copy()
if len(viol):
    viol["exceso"] = viol["rj_portafolio"] - float(rj_max)
    print("\nTop violaciones (mayor exceso):")
    cols = [c for c in ["sol_id","tipo","n_skus","capital_pen","ingresos_pen","rj_portafolio"] if c in viol.columns]
    print(viol.sort_values("exceso", ascending=False).head(10)[cols].to_string(index=False))

# Revisar si el portafolio “SEGURO” vs otros cambia
if "tipo" in df.columns:
    print("\nFactibilidad por tipo:")
    g = df.groupby("tipo")["factible_rj"].agg(["count","sum"])
    g = g.rename(columns={"count":"n","sum":"n_factibles"})
    g["pct_factible"] = g["n_factibles"]/g["n"]*100
    print(g.sort_values("pct_factible", ascending=False).to_string())
