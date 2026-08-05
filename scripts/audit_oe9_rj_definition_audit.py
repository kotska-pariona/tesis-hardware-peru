import pandas as pd
import numpy as np

path = "data/features/oe9_feature_matrix.csv"
df = pd.read_csv(path, encoding="utf-8")

# parse r_j
df["r_j"] = pd.to_numeric(df.get("r_j", pd.Series([np.nan]*len(df))), errors="coerce")
df = df[df["r_j"].notna()].copy()

print("=== A) AUDIT r_j DEFINITION / DISCRETIZACION ===")
print("Filas con r_j:", len(df))
print("Stats r_j:")
print(df["r_j"].describe())

# valores únicos frecuentes (si son discretos)
vc = df["r_j"].value_counts().sort_values(ascending=False)
print("\nTop valores por frecuencia (r_j):")
print(vc.head(15).to_string())

# etiquetas/campos candidatos
label_cols = [c for c in df.columns if "obsol" in c.lower() or "riesg" in c.lower() or "risk" in c.lower() or "label" in c.lower()]
print("\nColumnas candidatas de etiquetas/flags:")
print(label_cols)

# si existe label_obsolescencia, comparar medias
if "label_obsolescencia" in df.columns:
    print("\nComparativo r_j por label_obsolescencia:")
    grp = df.groupby("label_obsolescencia")["r_j"].agg(["count","mean","median","min","max"]).sort_values("mean", ascending=False)
    print(grp.to_string())

# si existe alguna columna binaria numérica tipo 0/1 (riesgo), correlación rápida
cand_numeric = []
for c in label_cols:
    if pd.api.types.is_numeric_dtype(df[c]):
        cand_numeric.append(c)
print("\nColumnas numéricas detectadas entre candidatas:")
print(cand_numeric)

for c in cand_numeric[:10]:
    corr = df["r_j"].corr(df[c])
    print(f"- corr(r_j, {c}) = {corr}")

# Correlación con posibles features de precio/roi/costo para ver sesgos
corr_candidates = []
for c in ["roi_unitario_pct","ganancia_unitaria","precio_import_usd","costo_usd","venta_usd","ganancia","precio","costo"]:
    if c in df.columns:
        corr_candidates.append(c)

print("\nCorrelaciones (si existen columnas compatibles):")
for c in corr_candidates:
    try:
        x = pd.to_numeric(df[c], errors="coerce")
        corr = df["r_j"].corr(x)
        print(f"- corr(r_j, {c}) = {corr}")
    except:
        pass

# muestra extremos
print("\n--- Top 10 r_j más altos ---")
cols = [c for c in ["sku","producto","categoria","label_obsolescencia","r_j"] if c in df.columns]
print(df.sort_values("r_j", ascending=False).head(10)[cols].to_string(index=False))

print("\n--- Bottom 10 r_j más bajos ---")
print(df.sort_values("r_j", ascending=True).head(10)[cols].to_string(index=False))
