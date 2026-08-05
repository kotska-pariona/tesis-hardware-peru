import pandas as pd

path = "data/features/oe9_feature_matrix.csv"
df = pd.read_csv(path, encoding="utf-8")

print("=== BASIC AUDIT: oe9_feature_matrix.csv ===")
print("Shape:", df.shape)
print("Columns:", list(df.columns))

required = ["roi_unitario_pct", "ganancia_unitaria", "r_j", "categoria", "precio_import_usd"]
missing = [c for c in required if c not in df.columns]
if missing:
    print("\n❌ FALTAN COLUMNAS REQUERIDAS:", missing)
else:
    print("\n✅ Columnas requeridas presentes.")

for c in required:
    if c in df.columns:
        n_nan = int(df[c].isna().sum())
        print(f"NaNs {c}: {n_nan}")

print("\n--- ROI distribution ---")
if "roi_unitario_pct" in df.columns:
    s = pd.to_numeric(df["roi_unitario_pct"], errors="coerce")
    print(s.describe())
