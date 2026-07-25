import pandas as pd
df = pd.read_csv("data/processed/pe5_decisions.csv")

print("=== TOP BUY con precios ===")
top = df[df["decision"]=="BUY"].nlargest(15, "roi_pct")[
    ["title","price_import_usd","price_local_pen","roi_pct","score_final"]
]
for _, r in top.iterrows():
    print(f"  ROI={r['roi_pct']:6.1f}% | imp=${r['price_import_usd']:6.1f} | loc=S/{r['price_local_pen']:7.1f} | {r['title'][:55]}")

print(f"\n=== Distribución price_local_pen (BUY) ===")
print(df[df["decision"]=="BUY"]["price_local_pen"].describe().round(1))

print(f"\n=== Lógica WAIT — ver score_final de HOLD ===")
hold = df[df["decision"]=="HOLD"]["score_final"]
print(f"  HOLD score: min={hold.min():.1f} | max={hold.max():.1f} | mean={hold.mean():.1f}")

print(f"\n=== Buscar umbral WAIT en código ===")
import pathlib as _pl
lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()
for i, l in enumerate(lines, start=1):
    if "WAIT" in l and ("score" in l or "thresh" in l or "umbral" in l or "<" in l or ">" in l):
        print(f"  {i:4d} | {l}")

print(f"\n=== Deduplicación — títulos repetidos en BUY ===")
dup = df[df["decision"]=="BUY"].groupby("title").size()
print(f"  Títulos únicos BUY: {len(dup)} de {(df['decision']=='BUY').sum()} total")
print(f"  Títulos con >5 repeticiones: {(dup>5).sum()}")
