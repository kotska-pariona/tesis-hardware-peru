import numpy as np
import pandas as pd

path = "data/features/oe9_feature_matrix.csv"
df = pd.read_csv(path, encoding="utf-8")

df["r_j"] = pd.to_numeric(df["r_j"], errors="coerce")
df["categoria"] = df.get("categoria", pd.Series(["NA"]*len(df))).astype(str)
df = df[df["r_j"].notna()].copy()

RJ_MAX = 0.35
np.random.seed(42)

print("=== C) Impacto por categorías en violación RJ_MAX ===")
print("RJ_MAX:", RJ_MAX)
print("Filas:", len(df))
print("r_j stats:", df["r_j"].describe().to_string())

# categorías relevantes (ordenadas por media r_j)
cat_summary = df.groupby("categoria")["r_j"].agg(["count","mean","median","min","max"]).sort_values("mean", ascending=False)
print("\n--- Media r_j por categoría (desc) ---")
print(cat_summary.head(15).round(4).to_string())

# categorías con r_j alto (media > RJ_MAX o median > RJ_MAX)
high_cats = cat_summary[cat_summary["median"] > RJ_MAX].index.tolist()
print("\nCategorías con median(r_j) > RJ_MAX:", high_cats)

# simulación: portafolio con n skus, tomando proporciones aleatorias pero controlando inclusión de RAM etc.
N_TESTS = 500
N_LIST = [5, 10, 15]

idx_all = df.index.values
cats = df["categoria"].values

# función de muestreo por "incluir categoría X con prob p"
def simulate(n, force_cats=None):
    force_cats = force_cats or []
    ok = 0
    viol = 0
    for _ in range(N_TESTS):
        chosen = set()
        # forzar: tomar al menos 1 sku por categoría forzada si existe
        for c in force_cats:
            pool = df[df["categoria"] == c].index.values
            if len(pool) > 0:
                chosen.add(int(np.random.choice(pool)))
        # completar con random de todo
        while len(chosen) < n:
            chosen.add(int(np.random.choice(idx_all)))
        chosen_idx = list(chosen)[:n]
        rj_port = float(df.loc[chosen_idx, "r_j"].mean())
        if rj_port <= RJ_MAX:
            ok += 1
        else:
            viol += 1
    return ok, viol

for n in N_LIST:
    if n > len(df): 
        continue
    print(f"\n--- n={n} ---")

    # escenarios
    scenarios = [
        ([], "Sin forzar categorías altas"),
        (["RAM"], "Forzar RAM"),
        (["CPU"], "Forzar CPU"),
        (["MOTHERBOARD"], "Forzar MOTHERBOARD"),
        (["RAM","CPU"], "Forzar RAM+CPU"),
        (["RAM","MOTHERBOARD"], "Forzar RAM+MB"),
        (["CPU","MOTHERBOARD"], "Forzar CPU+MB"),
    ]
    for force, label in scenarios:
        ok, viol = simulate(n, force_cats=force)
        pct = ok / N_TESTS * 100
        print(f"{label:25s} -> factible ~ {pct:.2f}% (ok={ok}/{N_TESTS})")
