import numpy as np
import pandas as pd

path = "data/features/oe9_feature_matrix.csv"
df = pd.read_csv(path, encoding="utf-8")

df["r_j"] = pd.to_numeric(df["r_j"], errors="coerce")
df["categoria"] = df.get("categoria", pd.Series(["NA"]*len(df))).astype(str)

df = df[df["r_j"].notna()].copy()
print("=== B) Sensitivity de RJ_MAX vs factibilidad aproximada ===")
print("Filas con r_j:", len(df))
print("Stats r_j:", df["r_j"].describe().to_string())

# Parámetros
RJ_LIST = [0.35, 0.5, 0.75, 0.95]
N_LIST = [5, 10, 15]
N_TESTS = 200
np.random.seed(42)

rj = df["r_j"].values
cats = df["categoria"].values
idx_all = df.index.values

for RJ_MAX in RJ_LIST:
    print(f"\n--- RJ_MAX = {RJ_MAX} ---")
    for n in N_LIST:
        if n > len(df):
            continue
        ok = 0
        for _ in range(N_TESTS):
            idx = np.random.choice(idx_all, size=n, replace=False)

            # aproximación: rj_port como promedio simple (porque no tenemos unidades/capital aquí)
            # si quieres, lo hacemos ponderado por capital también, pero primero lo básico.
            rj_port = float(df.loc[idx, "r_j"].mean())
            if rj_port <= RJ_MAX:
                ok += 1
        pct = ok / N_TESTS * 100
        print(f"n={n:>2} -> prob.aprox factible: {pct:.2f}% (ok={ok}/{N_TESTS})")
