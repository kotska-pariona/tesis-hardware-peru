# =============================================================================
# HDS-ROI v6.0 — Normalizador MASTER v2.0
#
# N-7:  Limpia price_pen de fuentes no-locales (FIX raiz contaminacion)
# N-8:  Calcula markup real por categoria -> markup_real.json
# N-9:  Deduplica por (sku, source, timestamp)
# N-10: Normaliza columnas de Newegg al esquema estandar
# =============================================================================

import pandas as pd
import numpy as np
import json
import re
from pathlib import Path
from datetime import datetime

# ── Rutas ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent.parent
MASTER_IN   = BASE_DIR / "data" / "raw" / "MASTER_hardware_peru.csv"
MASTER_OUT  = BASE_DIR / "data" / "raw" / "MASTER_normalizado.csv"
MARKUP_JSON = BASE_DIR / "data" / "raw" / "markup_real.json"

# ── Fuentes locales PE (unicas con price_pen valido) ─────────────────────────
FUENTES_LOCALES = [
    "falabella", "hiraoka", "ripley", "coolbox",
    "mercadolibre", "linio", "saga", "oechsle",
]

# ── Categorias validas ────────────────────────────────────────────────────────
CATEGORIAS_VALIDAS = {
    "psu", "motherboard", "cooler", "case", "ram",
    "cpu", "ssd", "hdd", "gpu", "laptop", "monitor", "otro",
}

# ── Titulos sucios ────────────────────────────────────────────────────────────
TITULO_SUCIO_RE = re.compile(
    r"(for parts|not working|broken|defective|as.is|untested|damaged)",
    re.IGNORECASE,
)

# ── Markup fallback por categoria ─────────────────────────────────────────────
MARKUP_FALLBACK = {
    "psu":         1.85,
    "motherboard": 1.75,
    "cooler":      2.00,
    "case":        1.80,
    "ram":         1.60,
    "cpu":         1.55,
    "ssd":         1.45,
    "hdd":         1.40,
    "gpu":         1.20,
    "laptop":      1.55,
    "monitor":     1.40,
    "otro":        1.50,
}


def es_local(source: str) -> bool:
    s = str(source).lower()
    return any(f in s for f in FUENTES_LOCALES)


def normalizar_newegg(df: pd.DataFrame) -> pd.DataFrame:
    """N-10: Mapea columnas no-estandar de Newegg al esquema MASTER."""
    renombrar = {
        "titulo":    "title",
        "precio":    "price_usd",
        "categoria": "category",
        "tienda":    "source",
        "marca":     "brand",
        "modelo":    "model",
        "rating":    "rating",
        "reviews":   "reviews",
    }
    mask_newegg = df["source"].str.lower().str.contains("newegg", na=False)
    if mask_newegg.sum() == 0:
        return df
    for old, new in renombrar.items():
        if old in df.columns and new not in df.columns:
            df.loc[mask_newegg, new] = df.loc[mask_newegg, old]
    return df


def calcular_markup_real(df: pd.DataFrame) -> dict:
    """N-8: Calcula markup real comparando precio compra (USD) vs venta (PEN/USD)."""
    TC = 3.75  # tipo de cambio referencial

    mask_compra = df["source"].apply(lambda x: not es_local(str(x)))
    mask_venta  = df["source"].apply(es_local)

    df_compra = df[mask_compra & df["price_usd"].notna() & (df["price_usd"] > 0)].copy()
    df_venta  = df[mask_venta  & df["price_pen"].notna() & (df["price_pen"] > 0)].copy()

    if df_venta.empty or df_compra.empty:
        print("      ⚠️  Sin datos suficientes para markup real — usando fallback")
        return {}

    df_venta["price_usd_equiv"] = df_venta["price_pen"] / TC

    markups = {}
    cats_comunes = set(df_compra["hw_type"].dropna()) & set(df_venta["hw_type"].dropna())

    print(f"      💰 Precio medio COMPRA vs VENTA por categoria:")
    print(f"         {'categoria':<15} {'compra_usd':>10} {'venta_usd':>10} {'markup':>8}")

    for cat in sorted(cats_comunes):
        if cat not in CATEGORIAS_VALIDAS or cat == "otro":
            continue
        c_med = df_compra[df_compra["hw_type"] == cat]["price_usd"].median()
        v_med = df_venta[df_venta["hw_type"] == cat]["price_usd_equiv"].median()
        if pd.isna(c_med) or pd.isna(v_med) or c_med <= 0:
            continue
        mk = round(v_med / c_med, 3)
        if 1.05 <= mk <= 5.0:
            markups[cat] = mk
            print(f"         {cat:<15} {c_med:>10.2f} {v_med:>10.2f} {mk:>8.3f}x")

    return markups


def main():
    print("=" * 60)
    print("  HDS-ROI — Normalizador MASTER v2.0")
    print("=" * 60)
    print()

    # ── [1/9] Cargar ─────────────────────────────────────────────
    print(f"[1/9] Cargando {MASTER_IN.name} ...")
    if not MASTER_IN.exists():
        print(f"      ❌ No encontrado: {MASTER_IN}")
        return
    df = pd.read_csv(MASTER_IN, low_memory=False)
    print(f"      Shape original: {df.shape}")

    # ── [2/9] N-9: Deduplicar ────────────────────────────────────
    print(f"\n[2/9] N-9: Deduplicando por (sku, source, timestamp) ...")
    cols_dedup = [c for c in ["sku", "source", "timestamp"] if c in df.columns]
    if cols_dedup:
        antes = len(df)
        df = df.drop_duplicates(subset=cols_dedup, keep="last")
        print(f"      Duplicados eliminados: {antes - len(df):,}")
    else:
        print(f"      ⚠️  Columnas dedup no encontradas: {cols_dedup} — omitiendo")
    print(f"      Registros tras dedup: {len(df):,}")

    # ── [3/9] N-10: Normalizar Newegg ────────────────────────────
    print(f"\n[3/9] N-10: Normalizando columnas Newegg ...")
    df = normalizar_newegg(df)

    # -- [4/9] N-1: Normalizar category ---
    print("\n[4/9] N-1: Normalizando hw_type/category ...")
    if "category_label" in df.columns and "hw_type" not in df.columns:
        df["hw_type"] = df["category_label"].str.lower().str.strip()
    elif "hw_type" not in df.columns and "category" in df.columns:
        df["hw_type"] = df["category"].str.lower().str.strip()
    if "hw_type" in df.columns:
        df["hw_type"] = df["hw_type"].where(
            df["hw_type"].isin(CATEGORIAS_VALIDAS), other="otro"
        )
        print("      hw_type no-nulos: " + str(df["hw_type"].notna().sum()) + " / " + str(len(df)))
        # FIX-N13: Mapear category -> hw_type para fuentes locales
        if "category" in df.columns:
            _CAT_MAP = {
                "laptops": "laptop",       "computadoras": "laptop",
                "memorias_ram": "ram",
                "tarjetas_video": "gpu",
                "procesadores": "cpu",     "CPU": "cpu",
                "MOTHERBOARD": "motherboard",
                "CASE": "case",
                "COOLER": "cooler",
                "discos_ssd": "ssd",
                "monitores": "monitor",
                "fuentes_poder": "psu",    "PSU": "psu",
            }
            _mask_otro = (df["hw_type"] == "otro") | (df["hw_type"].isna())
            _mapped = df.loc[_mask_otro, "category"].map(_CAT_MAP)
            _fixed = _mapped.notna().sum()
            df.loc[_mask_otro & _mapped.notna(), "hw_type"] = _mapped[_mapped.notna()]
            print("      FIX-N13: " + str(_fixed) + " registros reclasificados desde category")
            print("      hw_type post-fix: " + str(df["hw_type"].value_counts().head(12).to_dict()))
    else:
        print("      Sin columna hw_type — omitiendo")

    # ── [5/9] N-2: Normalizar SKU ────────────────────────────────
    print(f"\n[5/9] N-2: Normalizando SKU ...")
    if "sku" not in df.columns:
        if "item_id" in df.columns:
            df["sku"] = df["item_id"].astype(str)
        elif "asin" in df.columns:
            df["sku"] = df["asin"].astype(str)
        else:
            df["sku"] = [f"sku_{i}" for i in range(len(df))]
    df["sku"] = df["sku"].astype(str).str.strip()
    nulos_sku = df["sku"].isin(["nan", "", "None"]).sum()
    print(f"      SKUs nulos/vacios: {nulos_sku:,}")

    # ── [6/9] N-3: Filtrar titulos sucios ────────────────────────
    print(f"\n[6/9] N-3: Filtrando titulos sucios ...")
    if "title" in df.columns:
        mask_sucio = df["title"].str.contains(TITULO_SUCIO_RE, na=False)
        print(f"      Titulos sucios eliminados: {mask_sucio.sum():,}")
        df = df[~mask_sucio].copy()
    else:
        print("      ⚠️  Sin columna title — omitiendo")
    print(f"      Registros restantes: {len(df):,}")

    # ── [7/9] N-5: Ajustar precios por condicion eBay ────────────
    print(f"\n[7/9] N-5: Ajustando precios por condicion (eBay) ...")
    if "condition" in df.columns and "price_usd" in df.columns:
        mask_ebay = df["source"].str.lower().str.contains("ebay", na=False)
        mask_used = df["condition"].str.lower().str.contains(
            "used|refurb|pre.owned", na=False, regex=True
        )
        ajustados = (mask_ebay & mask_used).sum()
        df.loc[mask_ebay & mask_used, "price_usd"] *= 0.85
        print(f"      Precios ajustados (used/refurb eBay): {ajustados:,}")
    else:
        print("      ⚠️  Sin columna condition — omitiendo")

    # ── [8/9] N-7: Limpiar price_pen de no-locales ───────────────
    print(f"\n[8/9] N-7: Limpiando price_pen de fuentes no-locales ...")
    if "price_pen" not in df.columns:
        df["price_pen"] = np.nan
    mask_local    = df["source"].apply(es_local)
    mask_no_local = ~mask_local
    pen_contaminados = df.loc[mask_no_local, "price_pen"].notna().sum()
    df.loc[mask_no_local, "price_pen"] = np.nan
    pen_validos = df["price_pen"].notna().sum()
    print(f"      Fuentes locales:              {mask_local.sum():,} registros")
    print(f"      price_pen -> NaN (no-local):  {pen_contaminados:,} registros")
    print(f"      price_pen validos restantes:  {pen_validos:,}")
    if pen_contaminados == 0:
        print("      ℹ️  No habia contaminacion previa (ya estaba limpio)")
    if pen_validos == 0:
        print("      ⚠️  Sin datos locales PE — scrapers locales no corrieron")

    # FIX-N11: source_rol requerido por pe2_multihorizonte.py
    _FUENTES_LOCALES = {
        "falabella_pe","falabella","hiraoka_pe","hiraoka",
        "ripley_pe","ripley","coolbox_pe","coolbox",
        "linio_pe","mercadolibre_pe","juntoz_pe",
    }
    df["source_rol"] = df["source"].apply(
        lambda x: "venta" if str(x).lower() in _FUENTES_LOCALES else "compra"
    )
    print("      FIX-N11 source_rol: " + str(df["source_rol"].value_counts().to_dict()))

    # ── [9/9] N-8: Calcular markup real ──────────────────────────
    print(f"\n[9/9] N-8: Calculando markup real por categoria ...")
    markups_reales = calcular_markup_real(df)

    if markups_reales:
        # Combinar con fallback para categorias sin datos
        markup_final = {**MARKUP_FALLBACK, **markups_reales}
        MARKUP_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(MARKUP_JSON, "w", encoding="utf-8") as f:
            json.dump(markup_final, f, indent=2, ensure_ascii=False)
        print(f"      ✅ markup_real.json guardado: {len(markups_reales)} categorias con datos reales")
        print(f"         {markup_final}")
    else:
        print("      ⚠️  Sin datos para markup real — markup_real.json NO generado")
        print("      ℹ️  pe2_multihorizonte.py usara MARKUP_HW hardcodeado")

    # ── Guardar MASTER normalizado ────────────────────────────────
    print(f"\n[Guardando] MASTER_normalizado.csv ...")
    MASTER_OUT.parent.mkdir(parents=True, exist_ok=True)

    print(f"      📊 Registros por fuente (top 10):")
    if "source" in df.columns:
        top_fuentes = df["source"].value_counts().head(10)
        for fuente, cnt in top_fuentes.items():
            local_tag = " [LOCAL]" if es_local(str(fuente)) else ""
            print(f"         {fuente:<30} {cnt:>8,}{local_tag}")

    df.to_csv(MASTER_OUT, index=False, encoding="utf-8")
    size_mb = MASTER_OUT.stat().st_size / 1024 / 1024
    print(f"\n      ✅ Guardado: {MASTER_OUT.name} ({size_mb:.1f} MB)")
    print(f"      ✅ Registros finales: {len(df):,}")
    print()
    print("=" * 60)
    print("  ✅ Normalizacion completada")
    print("=" * 60)


if __name__ == "__main__":
    main()
