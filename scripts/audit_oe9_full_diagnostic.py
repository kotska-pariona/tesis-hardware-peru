import pandas as pd
import numpy as np

path = "data/features/oe9_feature_matrix.csv"
df = pd.read_csv(path, encoding="utf-8")
df["r_j"] = pd.to_numeric(df["r_j"], errors="coerce")

print("=== DIAGNÓSTICO A: Lógica de r_j ===")
if "label_obsolescencia" in df.columns:
    print(df.groupby("label_obsolescencia")["r_j"].agg(["mean", "median", "count"]))

print("\n=== DIAGNÓSTICO B: Sensibilidad RJ_MAX ===")
thresholds = [0.35, 0.5, 0.75, 0.95]
for t in thresholds:
    n_tests = 100
    factibles = 0
    for _ in range(n_tests):
        sample = df.sample(n=10)
        if sample["r_j"].mean() <= t:
            factibles += 1
    print(f"RJ_MAX {t}: {factibles}% de portafolios aleatorios son factibles.")

print("\n=== DIAGNÓSTICO C: Correlación con Objetivos ===")
corr = df[["r_j", "roi_unitario_pct", "ganancia_unitaria"]].corr()
print(corr)
