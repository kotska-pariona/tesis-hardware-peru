import pandas as pd
import numpy as np

path = "data/features/oe9_feature_matrix.csv"
df = pd.read_csv(path, encoding="utf-8")

df["r_j"] = pd.to_numeric(df["r_j"], errors="coerce")
df = df[df["r_j"].notna()].copy()

RJ_MAX = 0.35

print("=== AUDIT r_j DISTRIBUTION ===")
print("Rows total:", len(pd.read_csv(path, encoding="utf-8")))
print("Rows con r_j:", len(df))

print("\nStats r_j:")
print(df["r_j"].describe())

# Conteos frente a RJ_MAX
ok = (df["r_j"] <= RJ_MAX)
print(f"\nCount r_j <= {RJ_MAX} :", int(ok.sum()))
print(f"Count r_j >  {RJ_MAX} :", int((~ok).sum()))
print(f"Pct <= {RJ_MAX} :", round(ok.mean() * 100, 2), "%")

# Por categoría
if "categoria" in df.columns:
    df["categoria"] = df["categoria"].astype(str)
    grp = df.groupby("categoria")["r_j"]
    summary = grp.agg(["count", "mean", "median", "min", "max"])
    summary["pct_le"] = grp.apply(lambda s: (s <= RJ_MAX).mean()).values
    summary = summary.sort_values("pct_le", ascending=False)
    print("\n--- r_j por categoría (top 10 por %<=RJ_MAX) ---")
    print(summary.head(10).round(4).to_string())

    print("\n--- r_j por categoría (más problemáticas: %>RJ_MAX) ---")
    summary2 = summary.sort_values("pct_le", ascending=True)
    print(summary2.head(10).round(4).to_string())

# Muestra algunos SKUs con r_j alto
top = df.sort_values("r_j", ascending=False).head(15)
cols = [c for c in ["sku","producto","categoria","r_j","label_obsolescencia"] if c in top.columns]
print("\n--- Top 15 r_j más altos ---")
print(top[cols].to_string(index=False))
