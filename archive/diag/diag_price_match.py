import pandas as pd
df = pd.read_csv("data/processed/pe5_decisions.csv")

print("=== Distribución price_local_pen ===")
print(df["price_local_pen"].describe().round(1))

print(f"\n=== ¿Cuántos tienen price_local_pen == 3000? ===")
exact = (df["price_local_pen"] == 3000.0).sum()
print(f"  {exact} de {len(df)} ({exact/len(df)*100:.1f}%)")

print(f"\n=== Valores únicos de price_local_pen (top 20) ===")
print(df["price_local_pen"].value_counts().head(20))

print(f"\n=== BUY con price_local_pen != 3000 ===")
real = df[(df["decision"]=="BUY") & (df["price_local_pen"] != 3000.0)]
print(f"  Count: {len(real)}")
if len(real):
    print(real[["title","price_import_usd","price_local_pen","roi_pct"]].head(10).to_string())
