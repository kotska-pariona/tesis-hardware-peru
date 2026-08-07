import pandas as pd
df = pd.read_csv("data/processed/pe5_decisions.csv")

print("=== HOLD con ROI positivo o cercano a 0 ===")
pos = df[(df["decision"]=="HOLD") & (df["roi_pct"] > -10)].sort_values("roi_pct", ascending=False)
print(f"  Count: {len(pos)}")
print(pos[["title","price_import_usd","price_local_pen","roi_pct","score_final"]].head(10).to_string())

print(f"\n=== Distribución ROI (todos) ===")
print(df["roi_pct"].describe().round(1))

print(f"\n=== ¿Cuántos tienen ROI > 0? ===")
print(f"  ROI > 0:   {(df['roi_pct'] > 0).sum()}")
print(f"  ROI > 10:  {(df['roi_pct'] > 10).sum()}")
print(f"  ROI > 20:  {(df['roi_pct'] > 20).sum()}")

print(f"\n=== price_local_pen distribución ===")
print(df["price_local_pen"].describe().round(1))

print(f"\n=== Ver lógica de decisión BUY en código ===")
import pathlib as _pl
lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()
in_block = False
for i, l in enumerate(lines, start=1):
    if "def _make_decision" in l or ("decision" in l.lower() and "def " in l):
        in_block = True
    if in_block:
        print(f"  {i:4d} | {l}")
        if i > 480:
            break
