import pandas as pd
import numpy as np

PATH = "data/features/oe9_feature_matrix.csv"

def summarize(df, col):
    s = df[col]
    return {
        "min": float(pd.to_numeric(s, errors="coerce").min()),
        "p5": float(pd.to_numeric(s, errors="coerce").quantile(0.05)),
        "median": float(pd.to_numeric(s, errors="coerce").median()),
        "mean": float(pd.to_numeric(s, errors="coerce").mean()),
        "p95": float(pd.to_numeric(s, errors="coerce").quantile(0.95)),
        "max": float(pd.to_numeric(s, errors="coerce").max()),
        "n_nonnull": int(s.notna().sum()),
        "n_nan": int(s.isna().sum()),
    }

def main():
    df = pd.read_csv(PATH)
    
    required = ["precio_local_pen", "roi_unitario_pct", "ganancia_unitaria"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print("❌ Faltan columnas en la matriz:", missing)
        print("   Columnas disponibles:", list(df.columns))
        return
    
    # Convertimos a numérico por si viene como string
    for c in ["precio_local_pen", "roi_unitario_pct", "ganancia_unitaria"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    
    print("=== AUDITORÍA DE INTEGRIDAD FINANCIERA (sin costo explícito) ===")
    print(f"Total SKUs: {len(df)}\n")
    
    print("--- Estadísticos ---")
    for c in ["precio_local_pen", "roi_unitario_pct", "ganancia_unitaria"]:
        st = summarize(df, c)
        print(f"\n[{c}]")
        for k,v in st.items():
            print(f"  {k:>10}: {v}")
    
    # 1) Correlación: si todo está bien, roi_unitario_pct debería correlacionar con ganancia_unitaria
    corr = df[["roi_unitario_pct", "ganancia_unitaria"]].corr(numeric_only=True).iloc[0,1]
    print("\n--- Correlación ---")
    print(f"corr(roi_unitario_pct, ganancia_unitaria) = {corr:.4f}")
    
    # 2) Inconsistencias esperadas: ROI positivo pero ganancia negativa (o viceversa)
    # Ojo: roi_unitario_pct está en %; ganancia_unitaria en moneda.
    df["sign_roi"] = np.sign(df["roi_unitario_pct"].fillna(0))
    df["sign_gain"] = np.sign(df["ganancia_unitaria"].fillna(0))
    inconsist = df[(df["sign_roi"] > 0) & (df["sign_gain"] < 0) | (df["sign_roi"] < 0) & (df["sign_gain"] > 0)]
    
    print("\n--- Inconsistencias por signo ---")
    print(f"SKUs inconsistentes (ROI>0 & ganancia<0 o ROI<0 & ganancia>0): {len(inconsist)}")
    if len(inconsist):
        cols_show = ["sku","producto","categoria","precio_local_pen","roi_unitario_pct","ganancia_unitaria"]
        cols_show = [c for c in cols_show if c in df.columns]
        print("\nTop 15 inconsistentes:")
        print(inconsist.sort_values("ganancia_unitaria").head(15)[cols_show].to_string(index=False))
    
    # 3) Outliers de precios
    print("\n--- Outliers de precio_local_pen ---")
    q1 = df["precio_local_pen"].quantile(0.01)
    q99 = df["precio_local_pen"].quantile(0.99)
    out_price = df[(df["precio_local_pen"] <= q1) | (df["precio_local_pen"] >= q99)]
    print(f"SKUs fuera del percentil 1-99: {len(out_price)}")
    if len(out_price):
        cols_show = ["sku","producto","categoria","precio_local_pen","roi_unitario_pct","ganancia_unitaria"]
        cols_show = [c for c in cols_show if c in df.columns]
        print("\nEjemplos (outliers):")
        print(out_price.sort_values("precio_local_pen").head(10)[cols_show].to_string(index=False))
    
    # 4) Revisión directa: ¿cuántos ROI son positivos?
    pos = (df["roi_unitario_pct"] > 0).sum()
    neg = (df["roi_unitario_pct"] < 0).sum()
    zero = (df["roi_unitario_pct"] == 0).sum()
    print("\n--- Distribución ROI ---")
    print(f"ROI>0 : {pos}")
    print(f"ROI<0 : {neg}")
    print(f"ROI=0 : {zero}")
    
    # 5) Mostrar los top SKUs más rentables y los peores
    cols_show = ["sku","producto","categoria","precio_local_pen","roi_unitario_pct","ganancia_unitaria"]
    cols_show = [c for c in cols_show if c in df.columns]
    
    print("\n=== Top 10 ROI (más alto) ===")
    print(df.sort_values("roi_unitario_pct", ascending=False).head(10)[cols_show].to_string(index=False))
    
    print("\n=== Bottom 10 ROI (más bajo) ===")
    print(df.sort_values("roi_unitario_pct", ascending=True).head(10)[cols_show].to_string(index=False))

if __name__ == "__main__":
    main()