"""
OE4 — corpus_builder_v4.py
Etiqueta por MODELO (SKU) usando features temporales + señales de mercado.
Unidad de análisis: 1 fila = 1 SKU (modelo único)
"""
import re, json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

MASTER     = Path("data/raw/MASTER_hardware_peru.csv")
OUT_DIR    = Path("data")
OUT_CORPUS = OUT_DIR / "corpus_obsolescencia_v4.csv"
OUT_REPORT = OUT_DIR / "corpus_v4_report.json"
SEED       = 42
MIN_OBS    = 3       # mínimo de observaciones por SKU
N_PER_CLASS = 1000

LABEL_NAMES = {0: "VIGENTE", 1: "EN_RIESGO", 2: "OBSOLETO"}

# ── Reglas léxicas por generación tecnológica ─────────────────────────────────
GEN_RULES = {
    "obsoleto": [
        r'\bddr[123]\b', r'\bpc[23]\b',
        r'\bgtx\s*[4-9]\d{2}\b', r'\bgtx\s*10[0-9]{2}\b',
        r'\brtx\s*20[0-9]{2}\b',
        r'\brx\s*[45][0-9]{2}\b',
        r'\bi[357]-[2-7]\d{3}\w*\b',
        r'\bryzen\s*[123]\s*[123][0-9]{3}\b',
        r'\blga\s*(1151|1150|1155|1156|775|2011)\b',
        r'\bam[23]\+?\b', r'\bfm[12]\b',
        r'\bwindows\s*(7|8|xp|vista)\b',
    ],
    "en_riesgo": [
        r'\bddr4\b',
        r'\bgtx\s*16[0-9]{2}\b',
        r'\brtx\s*30[0-9]{2}\b', r'\brtx\s*40[0-9]{2}\b',
        r'\brx\s*6[0-9]{3}\b',  r'\brx\s*7[0-9]{3}\b',
        r'\bi[357]-1[0-4][0-9]{3}\w*\b',
        r'\bryzen\s*[57]\s*[5-7][0-9]{3}\b',
        r'\blga\s*1700\b', r'\bam4\b',
    ],
    "vigente": [
        r'\bddr5\b',
        r'\brtx\s*50[0-9]{2}\b', r'\brtx\s*[56][0-9]{3}\b',
        r'\brx\s*9[0-9]{3}\b',
        r'\bcore\s*ultra\b',
        r'\bryzen\s*[579]\s*[89][0-9]{3}\b',
        r'\blga\s*1851\b', r'\bam5\b',
        r'\bpcie\s*5\.0\b',
        r'\bwindows\s*11\b',
        r'\bi[357]-[12][0-9]{4}\w*\b',
    ],
}

def gen_score(title: str) -> dict:
    t = str(title).lower()
    scores = {"vigente": 0, "en_riesgo": 0, "obsoleto": 0}
    for gen, patterns in GEN_RULES.items():
        for p in patterns:
            if re.search(p, t):
                scores[gen] += 1
    return scores

def label_sku(row: pd.Series) -> tuple:
    """
    Etiqueta un SKU usando:
    1. Señales de mercado (condition, discount, precio tendencia)
    2. Señales léxicas del título representativo
    Retorna (label_id, confianza, razon)
    """
    title      = str(row.get("title_repr", "")).lower()
    cond_used  = float(row.get("pct_used", 0))
    disc_mean  = float(row.get("discount_mean", 0) or 0)
    price_trend= float(row.get("price_trend_pct", 0) or 0)  # % cambio precio
    n_obs      = int(row.get("n_obs", 1))

    # Señales de mercado
    market_score = {"vigente": 0, "en_riesgo": 0, "obsoleto": 0}

    # Condición
    if cond_used > 0.5:
        market_score["obsoleto"] += 3
    elif cond_used > 0.2:
        market_score["en_riesgo"] += 2

    # Descuento
    if disc_mean > 25:
        market_score["obsoleto"] += 2
    elif disc_mean > 10:
        market_score["en_riesgo"] += 2
    elif disc_mean < 3:
        market_score["vigente"] += 1

    # Tendencia de precio (caída = obsolescencia)
    if price_trend < -20:
        market_score["obsoleto"] += 3
    elif price_trend < -8:
        market_score["en_riesgo"] += 2
    elif price_trend > 0:
        market_score["vigente"] += 1

    # Señales léxicas
    gen = gen_score(title)

    # Combinar (léxico tiene más peso si es claro)
    total = {
        "vigente"  : market_score["vigente"]   + gen["vigente"]   * 2,
        "en_riesgo": market_score["en_riesgo"] + gen["en_riesgo"] * 2,
        "obsoleto" : market_score["obsoleto"]  + gen["obsoleto"]  * 2,
    }

    best = max(total, key=total.get)
    best_score = total[best]

    if best_score == 0:
        return -1, 0.0, "sin_señal"

    label_map = {"vigente": 0, "en_riesgo": 1, "obsoleto": 2}
    conf = min(best_score / 6.0, 1.0)
    return label_map[best], round(conf, 3), best

def build_texto(row: pd.Series) -> str:
    """Texto enriquecido para E5-large con señales de mercado."""
    parts = [str(row.get("title_repr", "")).strip()]

    # Señales de mercado como texto
    disc = row.get("discount_mean", 0) or 0
    if disc > 0:
        parts.append(f"descuento promedio: {disc:.1f}%")

    trend = row.get("price_trend_pct", 0) or 0
    if abs(trend) > 1:
        direction = "bajando" if trend < 0 else "subiendo"
        parts.append(f"precio {direction}: {abs(trend):.1f}%")

    cond_used = row.get("pct_used", 0) or 0
    if cond_used > 0.1:
        parts.append(f"condicion usado: {cond_used*100:.0f}%")

    if pd.notna(row.get("brand_repr")):
        parts.append(f"marca: {str(row['brand_repr']).lower().strip()}")

    if pd.notna(row.get("category_repr")):
        parts.append(f"categoria: {str(row['category_repr']).upper().strip()}")

    n_obs = row.get("n_obs", 1)
    parts.append(f"observaciones: {int(n_obs)}")

    return " | ".join(p for p in parts if str(p).strip())

def main():
    t0 = datetime.now()
    print("=" * 60)
    print("  OE4 corpus_builder_v4.py — Etiqueta por MODELO (SKU)")
    print(f"  Inicio: {t0.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ── Cargar MASTER ─────────────────────────────────────────────────────
    print(f"\n📂 Cargando {MASTER}...")
    COLS = ["sku", "title", "brand", "category", "source",
            "price_usd", "price_date", "discount_pct", "condition"]
    df = pd.read_csv(MASTER, usecols=lambda c: c in COLS,
                     low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
    df = df.dropna(subset=["sku", "title"]).copy()
    print(f"  Cargado: {len(df):,} filas | {df['sku'].nunique():,} SKUs únicos")

    # ── Filtrar SKUs con mínimo de observaciones ──────────────────────────
    obs_count = df.groupby("sku").size()
    valid_skus = obs_count[obs_count >= MIN_OBS].index
    df = df[df["sku"].isin(valid_skus)].copy()
    print(f"  SKUs con >= {MIN_OBS} obs: {df['sku'].nunique():,}")

    # ── Agregar por SKU ───────────────────────────────────────────────────
    print("\n📊 Agregando features por SKU (modelo)...")

    def agg_sku(g):
        prices = g["price_usd"].dropna()
        dates  = g["price_date"].dropna().sort_values()

        # Tendencia de precio: (último - primero) / primero * 100
        if len(prices) >= 2 and prices.iloc[0] > 0:
            trend = (prices.iloc[-1] - prices.iloc[0]) / prices.iloc[0] * 100
        else:
            trend = 0.0

        # % condición usado
        cond = g["condition"].fillna("New")
        pct_used = (cond.isin(["Used", "Open box"])).mean()

        return pd.Series({
            "n_obs"           : len(g),
            "title_repr"      : g["title"].mode().iloc[0] if len(g) > 0 else "",
            "brand_repr"      : g["brand"].mode().iloc[0] if g["brand"].notna().any() else None,
            "category_repr"   : g["category"].mode().iloc[0] if g["category"].notna().any() else None,
            "price_usd_mean"  : prices.mean() if len(prices) > 0 else None,
            "price_usd_std"   : prices.std()  if len(prices) > 1 else 0.0,
            "price_trend_pct" : round(trend, 2),
            "discount_mean"   : g["discount_pct"].mean(),
            "pct_used"        : round(pct_used, 3),
            "sources"         : ",".join(g["source"].dropna().unique()),
            "date_first"      : dates.min() if len(dates) > 0 else None,
            "date_last"       : dates.max() if len(dates) > 0 else None,
        })

    print("  Agregando (puede tardar ~30s)...")
    df_skus = df.groupby("sku").apply(agg_sku).reset_index()
    print(f"  SKUs agregados: {len(df_skus):,}")

    # ── Etiquetar por modelo ──────────────────────────────────────────────
    print("\n🏷️  Etiquetando por modelo...")
    results = df_skus.apply(label_sku, axis=1)
    df_skus["label_id"]  = results.apply(lambda x: x[0])
    df_skus["confianza"] = results.apply(lambda x: x[1])
    df_skus["razon"]     = results.apply(lambda x: x[2])
    df_skus["label"]     = df_skus["label_id"].map(LABEL_NAMES)

    df_labeled = df_skus[df_skus["label_id"] >= 0].copy()
    print(f"  Modelos etiquetados: {len(df_labeled):,} / {len(df_skus):,}")
    print(f"  Distribución:")
    for lid, lname in LABEL_NAMES.items():
        n = (df_labeled["label_id"] == lid).sum()
        print(f"    {lname:12s}: {n:>6,}")

    # ── Muestreo estratificado ────────────────────────────────────────────
    print(f"\n⚖️  Muestreo estratificado (hasta {N_PER_CLASS} por clase)...")
    parts = []
    actual_counts = {}
    for lid, lname in LABEL_NAMES.items():
        sub = df_labeled[df_labeled["label_id"] == lid]
        sub_sorted = sub.sort_values("confianza", ascending=False)
        n = min(N_PER_CLASS, len(sub_sorted))
        actual_counts[lname] = n
        parts.append(sub_sorted.head(n))
        print(f"    {lname:12s}: {n:>5,} seleccionados")

    df_balanced = pd.concat(parts, ignore_index=True)
    df_balanced = df_balanced.sample(frac=1, random_state=SEED).reset_index(drop=True)

    # ── Construir texto E5 ────────────────────────────────────────────────
    print("\n📝 Construyendo texto enriquecido para E5-large...")
    df_balanced["texto"] = df_balanced.apply(build_texto, axis=1)

    # ── Guardar ───────────────────────────────────────────────────────────
    cols_out = ["sku", "texto", "label", "label_id", "confianza", "razon",
                "title_repr", "brand_repr", "category_repr",
                "n_obs", "price_usd_mean", "price_trend_pct",
                "discount_mean", "pct_used", "sources"]
    cols_out = [c for c in cols_out if c in df_balanced.columns]
    df_balanced[cols_out].to_csv(OUT_CORPUS, index=False, encoding="utf-8")
    print(f"\n💾 Corpus guardado: {OUT_CORPUS}")
    print(f"   Shape: {df_balanced.shape}")

    # ── Reporte ───────────────────────────────────────────────────────────
    elapsed = (datetime.now() - t0).total_seconds()
    report = {
        "version"            : "v4",
        "unidad_analisis"    : "SKU (modelo)",
        "timestamp"          : datetime.now().isoformat(),
        "master_rows"        : len(df),
        "skus_totales"       : len(df_skus),
        "skus_etiquetados"   : len(df_labeled),
        "corpus_rows"        : len(df_balanced),
        "min_obs_por_sku"    : MIN_OBS,
        "actual_counts"      : actual_counts,
        "coverage_pct"       : round(len(df_labeled)/len(df_skus)*100, 2),
        "elapsed_sec"        : round(elapsed, 1),
    }
    with open(OUT_REPORT, "w") as f:
        json.dump(report, f, indent=2)
    print(f"💾 Reporte: {OUT_REPORT}")

    # Muestra de cada clase
    print("\n📋 Muestra por etiqueta:")
    for lid, lname in LABEL_NAMES.items():
        sub = df_balanced[df_balanced["label_id"] == lid].head(3)
        print(f"\n  [{lname}]")
        for _, r in sub.iterrows():
            print(f"    SKU: {r['sku']}")
            print(f"    Título: {str(r['title_repr'])[:80]}")
            print(f"    Razón: {r['razon']} | conf: {r['confianza']} | trend: {r.get('price_trend_pct','?')}%")

    print("\n" + "=" * 60)
    print(f"✅ Corpus v4 listo: {len(df_balanced):,} modelos etiquetados")
    print(f"   Tiempo: {elapsed:.1f}s")
    print(f"🔜 Siguiente: python scripts/oe4_e5_embedder_v2.py (apuntar a v4)")
    print("=" * 60)

if __name__ == "__main__":
    main()
