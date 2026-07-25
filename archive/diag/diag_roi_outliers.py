import pandas as pd
df = pd.read_csv("data/processed/pe5_decisions.csv")

print(f"Total: {len(df)}")
print(f"\n=== TOP 15 BUY por ROI ===")
top = df[df["decision"]=="BUY"].nlargest(15, "roi_pct")[
    ["title","roi_pct","score_final","price_import_usd","price_local_pen","regimen"]
]
for _, r in top.iterrows():
    print(f"  ROI={r['roi_pct']:7.1f}% | ${r['price_import_usd']:6.2f} | S/{r['price_local_pen']:7.1f} | {r['regimen']:12s} | {r['title'][:50]}")

print(f"\n=== Distribución ROI (BUY) ===")
buy = df[df["decision"]=="BUY"]["roi_pct"]
print(buy.describe().round(1))

print(f"\n=== Distribución price_import_usd (BUY) ===")
print(df[df["decision"]=="BUY"]["price_import_usd"].describe().round(2))

print(f"\n=== Decisiones ===")
print(df["decision"].value_counts())

print(f"\n=== BUY con price_import_usd < 5 ===")
cheap = df[(df["decision"]=="BUY") & (df["price_import_usd"] < 5)]
print(f"  Count: {len(cheap)}")
print(cheap[["title","price_import_usd","roi_pct"]].head(5).to_string())

print(f"\n=== Duplicados por título (BUY) ===")
dup = df[df["decision"]=="BUY"]["title"].value_counts()
print(dup[dup > 1].head(10))
