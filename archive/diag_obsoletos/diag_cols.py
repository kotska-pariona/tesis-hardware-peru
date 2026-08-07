import pandas as pd
df = pd.read_csv("data/raw/MASTER_hardware_peru.csv", low_memory=False, nrows=5)
print("=== Columnas del MASTER ===")
for c in df.columns:
    print(f"  {c}")
print(f"\n=== Muestra fila 0 ===")
print(df.iloc[0].to_string())
