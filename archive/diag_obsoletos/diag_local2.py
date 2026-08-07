import pandas as pd
df = pd.read_csv("data/raw/MASTER_hardware_peru.csv", low_memory=False)

print("=== Valores únicos de 'source' ===")
print(df["source"].value_counts().to_string())

print(f"\n=== Valores únicos de 'country' ===")
print(df["country"].value_counts().head(20).to_string())

print(f"\n=== Cómo separa pe5_agent local vs import ===")
import pathlib as _pl
lines = _pl.Path("agent/pe5_agent.py").read_text(encoding="utf-8").splitlines()
for i, l in enumerate(lines, start=1):
    if any(k in l for k in ["df_local", "df_import", "source_type", "local_sources", "import_sources", "falabella", "amazon", "country"]):
        if "=" in l or "filter" in l.lower() or "isin" in l or "==" in l:
            print(f"  {i:4d} | {l}")
