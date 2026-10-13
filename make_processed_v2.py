# make_processed_v2.py
# Genera data/processed_v2/{train,val,test}.csv con:
#   - 35 fechas (jul-sep) desde data/splits/
#   - group_key, brand_norm, model_norm, hw_type desde MASTER_normalizado + processed
#   - lags, MA, zscore desde data/features/
# Sin data leakage: stats calculadas SOLO sobre train

import pandas as pd
import numpy as np
import os, re, unicodedata
from pathlib import Path

# ── Rutas ─────────────────────────────────────────────────────────────────────
BASE = Path("D:/tesis-hardware-peru")
OUT  = BASE / "data" / "processed_v2"
OUT.mkdir(parents=True, exist_ok=True)

# ── 1. Cargar features/ (tiene lags, MA, zscore + 35 fechas) ──────────────────
print("Cargando features/...")
splits = {}
for name in ["train", "val", "test"]:
    df = pd.read_csv(BASE / "data" / "features" / f"{name}.csv", low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
    splits[name] = df
    print(f"  {name}: {len(df):,} registros | {df['price_date'].dt.date.nunique()} fechas "
          f"| {df['price_date'].min().date()} → {df['price_date'].max().date()}")

# ── 2. Cargar diccionario de normalización desde processed/ ──────────────────
# processed/ tiene brand_norm, model_norm, group_key, hw_type para 13 fechas
# Usamos como DICCIONARIO: sku → {brand_norm, model_norm, group_key, hw_type}
print("\nCargando diccionario de normalización...")
proc_parts = []
for name in ["train", "val", "test"]:
    p = pd.read_csv(BASE / "data" / "processed" / f"{name}.csv", low_memory=False,
                    usecols=["sku", "hw_type", "brand_norm", "model_norm",
                             "brand_model", "group_key", "source_rol"])
    proc_parts.append(p)

proc_dict = pd.concat(proc_parts, ignore_index=True)
proc_dict = proc_dict.dropna(subset=["sku"])

# Quedarse con la asignación más frecuente por sku (evitar conflictos)
sku_norm = (proc_dict
            .groupby("sku")[["hw_type","brand_norm","model_norm","brand_model","group_key","source_rol"]]
            .agg(lambda x: x.mode().iloc[0] if len(x) > 0 else np.nan)
            .reset_index())

print(f"  SKUs en diccionario: {len(sku_norm):,}")
print(f"  hw_type dist: {sku_norm['hw_type'].value_counts().head(5).to_dict()}")

# ── 3. Helpers de normalización para SKUs nuevos (no en diccionario) ──────────
HW_KEYWORDS = {
    "cpu":         ["ryzen","core i","intel","amd cpu","procesador","processor","threadripper","xeon","pentium","celeron"],
    "gpu":         ["rtx","gtx","rx ","radeon","geforce","nvidia","gpu","graphics","tarjeta de video"],
    "ram":         ["ddr4","ddr5","dimm","sodimm","memoria ram","ram ","gb ram"],
    "ssd":         ["ssd","nvme","m.2","solid state","disco solido"],
    "motherboard": ["motherboard","mainboard","placa madre","b550","b650","z790","x570","h610"],
    "monitor":     ["monitor","display","ips","va panel","hz ","144hz","165hz","240hz"],
    "psu":         ["psu","fuente","power supply","watt","650w","750w","850w","1000w"],
    "laptop":      ["laptop","notebook","gaming laptop","ultrabook"],
    "cooler":      ["cooler","disipador","aio","liquid cooling","fan cpu"],
    "case":        ["case","gabinete","torre","chasis","mid tower","full tower"],
}

def normalize_text(t):
    if not isinstance(t, str): return ""
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.lower().strip()

def infer_hw_type(title):
    t = normalize_text(str(title))
    for hw, kws in HW_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return hw
    return "otro"

def extract_brand(title):
    BRANDS = ["intel","amd","nvidia","asus","msi","gigabyte","asrock","evga",
              "corsair","kingston","crucial","samsung","western digital","wd",
              "seagate","lg","aoc","benq","viewsonic","cooler master","noctua",
              "be quiet","seasonic","thermaltake","fractal","nzxt","lian li",
              "hyperx","gskill","patriot","teamgroup","pny","zotac","xfx",
              "sapphire","powercolor","palit","gainward","inno3d","hp","dell",
              "lenovo","acer","toshiba","transcend"]
    t = normalize_text(str(title))
    for b in BRANDS:
        if b in t:
            return b.title()
    return "Unknown"

def extract_model(title, brand):
    t = normalize_text(str(title))
    b = normalize_text(str(brand))
    t = t.replace(b, "").strip()
    # Tomar primeras 4 palabras significativas
    words = [w for w in t.split() if len(w) > 1][:4]
    return " ".join(words).title() if words else "Unknown"

# ── 4. Aplicar diccionario + inferencia a cada split ─────────────────────────
print("\nAplicando normalización...")

COLS_KEEP = [
    "sku", "source", "price_usd", "price_date", "title", "brand",
    "condition", "category", "price_pen", "shipping_usd",
    "discount_pct", "rating", "reviews", "retailer",
    # lags y features temporales
    "price_usd_lag_1", "price_usd_lag_2", "price_usd_lag_9",
    "price_usd_ma_2", "price_usd_ma_3", "price_usd_ma_11",
    "price_usd_std_2", "price_usd_std_3", "price_usd_std_11",
    "price_usd_zscore_90",
]

for name, df in splits.items():
    print(f"\n  Procesando {name}...")

    # Merge con diccionario
    df = df.merge(sku_norm, on="sku", how="left")

    # Inferir para SKUs nuevos (no en diccionario)
    mask_new = df["hw_type"].isna()
    n_new = mask_new.sum()
    print(f"    SKUs nuevos (sin normalización): {n_new:,} ({100*n_new/len(df):.1f}%)")

    if n_new > 0:
        df.loc[mask_new, "hw_type"]    = df.loc[mask_new, "title"].apply(infer_hw_type)
        df.loc[mask_new, "brand_norm"] = df.loc[mask_new, "title"].apply(extract_brand)
        df.loc[mask_new, "model_norm"] = df.apply(
            lambda r: extract_model(r["title"], r["brand_norm"]) if pd.isna(r.get("model_norm")) else r["model_norm"],
            axis=1
        )
        df.loc[mask_new, "brand_model"] = (
            df.loc[mask_new, "brand_norm"].fillna("Unknown") + "|" +
            df.loc[mask_new, "model_norm"].fillna("Unknown")
        )
        df.loc[mask_new, "group_key"] = df.loc[mask_new, "brand_model"]
        df.loc[mask_new, "source_rol"] = "local"

    # Seleccionar columnas disponibles
    cols_available = [c for c in COLS_KEEP if c in df.columns]
    cols_norm = ["hw_type", "brand_norm", "model_norm", "brand_model", "group_key", "source_rol"]
    final_cols = cols_available + [c for c in cols_norm if c in df.columns]

    df_out = df[final_cols].copy()

    # Filtrar filas sin price_usd válido
    df_out = df_out[df_out["price_usd"].notna() & (df_out["price_usd"] > 0)]

    out_path = OUT / f"{name}.csv"
    df_out.to_csv(out_path, index=False, encoding="utf-8")

    print(f"    Guardado: {out_path}")
    print(f"    Registros: {len(df_out):,}")
    print(f"    Fechas: {df_out['price_date'].dt.date.nunique()} | "
          f"{df_out['price_date'].min().date()} → {df_out['price_date'].max().date()}")
    print(f"    hw_type dist: {df_out['hw_type'].value_counts().head(5).to_dict()}")
    print(f"    group_key nulos: {df_out['group_key'].isna().sum():,}")

print("\n✅ DONE — data/processed_v2/ listo")
print("Siguiente paso: python train_pe2_v52.py --data data/processed_v2/")
