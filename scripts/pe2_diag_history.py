"""
pe2_diag_history.py — ¿Cuánta historia temporal real tenemos?
=============================================================
El TFT reporta time_idx 0-8 = solo 9 días.
Este script investiga si el problema está en el preprocesamiento
o si realmente solo tenemos 9 días de datos scrapeados.
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("data/processed")
RAW_DIR  = Path("data/raw")

print("=" * 65)
print("  DIAGNÓSTICO: HISTORIA TEMPORAL REAL")
print("=" * 65)

# ── 1. Processed splits ──────────────────────────────────────
print("\n1. SPLITS PROCESADOS (data/processed/)")
for split in ["train", "val", "test"]:
    fp = DATA_DIR / f"{split}.csv"
    if not fp.exists():
        print(f"  {split}: NO EXISTE")
        continue
    df = pd.read_csv(fp, low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
    df = df[df["price_date"].notna()]
    print(f"\n  {split}.csv:")
    print(f"    Filas        : {len(df):,}")
    print(f"    Fecha min    : {df['price_date'].min().date()}")
    print(f"    Fecha max    : {df['price_date'].max().date()}")
    delta = (df['price_date'].max() - df['price_date'].min()).days
    print(f"    Rango días   : {delta} días")
    print(f"    Fechas únicas: {df['price_date'].dt.date.nunique()}")
    if "sku" in df.columns:
        print(f"    SKUs únicos  : {df['sku'].nunique():,}")
    if "source" in df.columns:
        print(f"    Fuentes      : {df['source'].unique().tolist()}")

# ── 2. Raw data ───────────────────────────────────────────────
print("\n" + "="*65)
print("2. DATOS RAW (data/raw/)")
if RAW_DIR.exists():
    raw_files = sorted(RAW_DIR.glob("*.csv")) + sorted(RAW_DIR.glob("*.parquet"))
    if not raw_files:
        raw_files = sorted(RAW_DIR.rglob("*.csv"))[:10]
    print(f"  Archivos encontrados: {len(raw_files)}")
    for fp in raw_files[:10]:
        try:
            if fp.suffix == ".parquet":
                df = pd.read_parquet(fp)
            else:
                df = pd.read_csv(fp, low_memory=False, nrows=50000)
            date_cols = [c for c in df.columns
                         if any(x in c.lower() for x in
                                ["date","fecha","time","timestamp"])]
            print(f"\n  {fp.name}:")
            print(f"    Filas  : {len(df):,}")
            print(f"    Cols   : {list(df.columns)[:8]}")
            for dc in date_cols[:2]:
                try:
                    s = pd.to_datetime(df[dc], errors="coerce").dropna()
                    if len(s) > 0:
                        delta = (s.max() - s.min()).days
                        print(f"    {dc}: {s.min().date()} → {s.max().date()} "
                              f"({delta} días, {s.dt.date.nunique()} fechas únicas)")
                except Exception:
                    pass
        except Exception as e:
            print(f"  {fp.name}: ERROR — {e}")
else:
    print("  data/raw/ no existe")

# ── 3. Análisis por SKU en train ──────────────────────────────
print("\n" + "="*65)
print("3. DISTRIBUCIÓN DE OBSERVACIONES POR SKU (train)")
fp = DATA_DIR / "train.csv"
if fp.exists():
    df = pd.read_csv(fp, low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
    df = df[df["price_date"].notna()]

    grp_cols = [c for c in ["sku","source"] if c in df.columns]
    obs_per_sku = df.groupby(grp_cols)["price_date"].agg(
        n="count",
        dias_rango=lambda x: (x.max()-x.min()).days + 1
    ).reset_index()

    print(f"\n  Observaciones por SKU:")
    print(f"    min    : {obs_per_sku['n'].min()}")
    print(f"    mediana: {obs_per_sku['n'].median():.0f}")
    print(f"    media  : {obs_per_sku['n'].mean():.1f}")
    print(f"    max    : {obs_per_sku['n'].max()}")
    print(f"    p25    : {obs_per_sku['n'].quantile(0.25):.0f}")
    print(f"    p75    : {obs_per_sku['n'].quantile(0.75):.0f}")

    print(f"\n  Distribución de frecuencia:")
    for n in [1, 2, 3, 5, 7, 9]:
        pct = (obs_per_sku['n'] <= n).mean() * 100
        cnt = (obs_per_sku['n'] <= n).sum()
        print(f"    SKUs con <= {n:2d} obs: {cnt:,} ({pct:.1f}%)")

    print(f"\n  Rango de días por SKU:")
    print(f"    min    : {obs_per_sku['dias_rango'].min()}")
    print(f"    mediana: {obs_per_sku['dias_rango'].median():.0f}")
    print(f"    max    : {obs_per_sku['dias_rango'].max()}")

# ── 4. Conclusión ─────────────────────────────────────────────
print("\n" + "="*65)
print("4. CONCLUSIÓN Y RECOMENDACIÓN")
print("="*65)
fp = DATA_DIR / "train.csv"
if fp.exists():
    df = pd.read_csv(fp, low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
    df = df[df["price_date"].notna()]
    delta = (df['price_date'].max() - df['price_date'].min()).days

    if delta < 14:
        print(f"\n  ⚠ CRÍTICO: Solo {delta} días de historia en train")
        print("  El TFT necesita mínimo 30 días para aprender patrones")
        print()
        print("  OPCIONES:")
        print("  A) Recolectar más datos históricos (scraping adicional)")
        print("  B) Usar encoder_length=2 y entrenar con todos los SKUs")
        print("  C) Cambiar a modelo tabular (LightGBM/XGBoost)")
        print("     → Con lag features ya calculadas, LightGBM puede dar")
        print("       MAPE < 2% con solo 9 días de historia")
    elif delta < 30:
        print(f"\n  ⚠ ADVERTENCIA: Solo {delta} días de historia")
        print("  Reducir encoder_length a 2-3 días")
    else:
        print(f"\n  ✓ {delta} días de historia disponibles")
        print("  El problema puede estar en el preprocesamiento")
        print("  Verificar pipeline DVC: ¿está filtrando fechas?")