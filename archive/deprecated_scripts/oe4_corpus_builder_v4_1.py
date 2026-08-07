"""
OE4 — corpus_builder_v4.1.py
Fixes:
  1. Filtrar títulos < 25 chars
  2. Calcular trend SOLO dentro de misma fuente (o normalizar a USD)
  3. Corregir reglas léxicas: Ryzen 7000 AM5 = EN_RIESGO (no OBSOLETO)
  4. Agregar regla: "(Renewed)" → OBSOLETO directo
"""
import re, json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

MASTER      = Path("data/raw/MASTER_hardware_peru.csv")
OUT_DIR     = Path("data")
OUT_CORPUS  = OUT_DIR / "corpus_obsolescencia_v4.csv"   # sobreescribe v4
OUT_REPORT  = OUT_DIR / "corpus_v4_report.json"
SEED        = 42
MIN_OBS     = 3
MIN_TITLE   = 25
N_PER_CLASS = 1000

LABEL_NAMES = {0: "VIGENTE", 1: "EN_RIESGO", 2: "OBSOLETO"}

GEN_RULES = {
    "obsoleto": [
        r'\bddr[123]\b', r'\bpc[23]\b',
        r'\bgtx\s*[4-9]\d{2}\b', r'\bgtx\s*10[0-9]{2}\b',
        r'\brtx\s*20[0-9]{2}\b',
        r'\brx\s*[45][0-9]{2}\b',
        r'\bi[357]-[2-7]\d{3}\w*\b',
        r'\bryzen\s*[123]\s*[123][0-9]{3}\b',   # Ryzen 1xxx/2xxx/3xxx
        r'\blga\s*(1151|1150|1155|1156|775|2011)\b',
        r'\bam[23]\+?\b', r'\bfm[12]\b',
        r'\bwindows\s*(7|8|xp|vista)\b',
        r'\brenewed\b', r'\brefurbish\w*\b',    # ← NUEVO: Renewed = obsoleto
        r'\bfor\s+parts\b',                      # ← NUEVO: "for parts"
    ],
    "en_riesgo": [
        r'\bddr4\b',
        r'\bgtx\s*16[0-9]{2}\b',
        r'\brtx\s*30[0-9]{2}\b', r'\brtx\s*40[0-9]{2}\b',
        r'\brx\s*6[0-9]{3}\b',   r'\brx\s*7[0-9]{3}\b',
        r'\bi[357]-1[0-4][0-9]{3}\w*\b',
        r'\bryzen\s*[57]\s*[5-7][0-9]{3}\b',
        r'\blga\s*1700\b', r'\bam4\b',
        # ← CORREGIDO: Ryzen 7000 AM5 es EN_RIESGO (transición, no obsoleto)
        r'\bryzen\s*[579]\s*7[0-9]{3}\w*\b',
        # DDR5 compatible con Ryzen 7000 no es obsoleto
    ],
    "vigente": [
        r'\bddr5\b',
        r'\brtx\s*50[0-9]{2}\b', r'\brtx\s*[56][0-9]{3}\b',
        r'\brx\s*9[0-9]{3}\b',
        r'\bcore\s*ultra\b',
        # ← CORREGIDO: Ryzen 9000 es VIGENTE
        r'\bryzen\s*[579]\s*9[0-9]{3}\w*\b',
        r'\bryzen\s*[579]\s*8[0-9]{3}\w*\b',    # Ryzen 8000 también vigente
        r'\blga\s*1851\b', r'\bam5\b',
        r'\bpcie\s*5\.0\b',
        r'\bwindows\s*11\b',
        r'\bi[357]-[12][0-9]{4}\w*\b',
        r'\bwifi\s*7\b', r'\bwi-fi\s*7\b',      # ← NUEVO: WiFi 7 = vigente
        r'\bgen\s*5\b', r'\bpcie\s*5\b',
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
    title       = str(row.get("title_repr", "")).lower()
    cond_used   = float(row.get("pct_used", 0) or 0)
    disc_mean   = float(row.get("discount_mean", 0) or 0)
    price_trend = float(row.get("price_trend_pct", 0) or 0)

    market = {"vigente": 0, "en_riesgo": 0, "obsoleto": 0}

    # Condición
    if cond_used > 0.5:
        market["obsoleto"] += 3
    elif cond_used > 0.2:
        market["en_riesgo"] += 2

    # Descuento (solo si trend no es extremo — evitar ruido multi-fuente)
    if abs(price_trend) < 40:
        if disc_mean > 25:
            market["obsoleto"] += 2
        elif disc_mean > 10:
            market["en_riesgo"] += 2
        elif disc_mean < 3:
            market["vigente"] += 1

        # Tendencia de precio limpia
        if price_trend < -20:
            market["obsoleto"] += 2
        elif price_trend < -8:
            market["en_riesgo"] += 1
        elif price_trend > 2:
            market["vigente"] += 1

    gen = gen_score(title)

    total = {
        "vigente"  : market["vigente"]   + gen["vigente"]   * 2,
        "en_riesgo": market["en_riesgo"] + gen["en_riesgo"] * 2,
        "obsoleto" : market["obsoleto"]  + gen["obsoleto"]  * 2,
    }

    best       = max(total, key=total.get)
    best_score = total[best]

    if best_score == 0:
        return -1, 0.0, "sin_señal"

    label_map = {"vigente": 0, "en_riesgo": 1, "obsoleto": 2}
    conf = min(best_score / 6.0, 1.0)
    return label_map[best], round(conf, 3), best

def build_texto(row: pd.Series) -> str:
    parts = [str(row.get("title_repr", "")).strip()]
    disc  = row.get("discount_mean", 0) or 0
    trend = row.get("price_trend_pct", 0) or 0
    cond_used = row.get("pct_used", 0) or 0

    if disc > 0 and abs(trend) < 40:
        parts.append(f"descuento promedio: {disc:.1f}%")
    if abs(trend) > 1 and abs(trend) < 40:
        direction = "bajando" if trend < 0 else "subiendo"
        parts.append(f"precio {direction}: {abs(trend):.1f}%")
    if cond_used > 0.1:
        parts.append(f"condicion usado: {cond_used*100:.0f}%")
    if pd.notna(row.get("brand_repr")):
        parts.append(f"marca: {str(row['brand_repr']).lower().strip()}")
    if pd.notna(row.get("category_repr")):
        parts.append(f"categoria: {str(row['category_repr']).upper().strip()}")
    parts.append(f"observaciones: {int(row.get('n_obs', 1))}")
    return " | ".join(p for p in parts if str(p).strip())

def main():
    t0 = datetime.now()
    print("=" * 60)
    print("  OE4 corpus_builder_v4.1 — Fix títulos + trend + reglas")
    print(f"  Inicio: {t0.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    COLS = ["sku","title","brand","category","source",
            "price_usd","price_date","discount_pct","condition"]
    df = pd.read_csv(MASTER, usecols=lambda c: c in COLS, low_memory=False)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
    df = df.dropna(subset=["sku","title"]).copy()
    df["title"] = df["title"].astype(str).str.strip()

    # Filtrar títulos basura desde el origen
    df = df[df["title"].str.len() >= MIN_TITLE].copy()
    print(f"  Tras filtro título >= {MIN_TITLE} chars: {len(df):,} filas | {df['sku'].nunique():,} SKUs")

    obs_count  = df.groupby("sku").size()
    valid_skus = obs_count[obs_count >= MIN_OBS].index
    df = df[df["sku"].isin(valid_skus)].copy()
    print(f"  SKUs con >= {MIN_OBS} obs: {df['sku'].nunique():,}")

    print("\n📊 Agregando features por SKU...")

    def agg_sku(g):
        # Trend SOLO usando fuente dominante (evitar mezcla USD/PEN)
        src_counts = g["source"].value_counts()
        main_src   = src_counts.index[0] if len(src_counts) > 0 else None
        g_src      = g[g["source"] == main_src] if main_src else g

        prices = g_src["price_usd"].dropna().sort_index()
        if len(prices) >= 2 and float(prices.iloc[0]) > 0:
            trend = (float(prices.iloc[-1]) - float(prices.iloc[0])) / float(prices.iloc[0]) * 100
        else:
            trend = 0.0

        cond     = g["condition"].fillna("New")
        pct_used = float((cond.isin(["Used","Open box"])).mean())

        title_candidates = g["title"][g["title"].str.len() >= MIN_TITLE]
        title_repr = title_candidates.mode().iloc[0] if len(title_candidates) > 0 else g["title"].mode().iloc[0]

        return pd.Series({
            "n_obs"           : len(g),
            "title_repr"      : title_repr,
            "brand_repr"      : g["brand"].mode().iloc[0] if g["brand"].notna().any() else None,
            "category_repr"   : g["category"].mode().iloc[0] if g["category"].notna().any() else None,
            "price_usd_mean"  : g_src["price_usd"].mean(),
            "price_usd_std"   : g_src["price_usd"].std() if len(g_src) > 1 else 0.0,
            "price_trend_pct" : round(trend, 2),
            "discount_mean"   : g["discount_pct"].mean(),
            "pct_used"        : round(pct_used, 3),
            "main_source"     : main_src,
            "sources"         : ",".join(g["source"].dropna().unique()),
        })

    print("  Agregando...")
    df_skus = df.groupby("sku").apply(agg_sku).reset_index()
    print(f"  SKUs agregados: {len(df_skus):,}")

    # Filtrar títulos basura post-agregación
    df_skus = df_skus[df_skus["title_repr"].str.len() >= MIN_TITLE].copy()
    print(f"  SKUs con título válido: {len(df_skus):,}")

    print("\n🏷️  Etiquetando por modelo...")
    results = df_skus.apply(label_sku, axis=1)
    df_skus["label_id"]  = results.apply(lambda x: x[0])
    df_skus["confianza"] = results.apply(lambda x: x[1])
    df_skus["razon"]     = results.apply(lambda x: x[2])
    df_skus["label"]     = df_skus["label_id"].map(LABEL_NAMES)

    df_labeled = df_skus[df_skus["label_id"] >= 0].copy()
    print(f"  Modelos etiquetados: {len(df_labeled):,} / {len(df_skus):,}")
    print(f"  Distribución bruta:")
    for lid, lname in LABEL_NAMES.items():
        n = (df_labeled["label_id"] == lid).sum()
        print(f"    {lname:12s}: {n:>6,}")

    print(f"\n⚖️  Muestreo estratificado (hasta {N_PER_CLASS}/clase)...")
    parts, actual_counts = [], {}
    for lid, lname in LABEL_NAMES.items():
        sub = df_labeled[df_labeled["label_id"] == lid].sort_values("confianza", ascending=False)
        n   = min(N_PER_CLASS, len(sub))
        actual_counts[lname] = n
        parts.append(sub.head(n))
        print(f"    {lname:12s}: {n:>5,}")

    df_bal = pd.concat(parts, ignore_index=True).sample(frac=1, random_state=SEED).reset_index(drop=True)
    df_bal["texto"] = df_bal.apply(build_texto, axis=1)

    cols_out = ["sku","texto","label","label_id","confianza","razon",
                "title_repr","brand_repr","category_repr",
                "n_obs","price_usd_mean","price_trend_pct",
                "discount_mean","pct_used","main_source","sources"]
    cols_out = [c for c in cols_out if c in df_bal.columns]
    df_bal[cols_out].to_csv(OUT_CORPUS, index=False, encoding="utf-8")

    elapsed = (datetime.now()-t0).total_seconds()
    report = {
        "version"         : "v4.1",
        "unidad_analisis" : "SKU (modelo)",
        "timestamp"       : datetime.now().isoformat(),
        "corpus_rows"     : len(df_bal),
        "actual_counts"   : actual_counts,
        "coverage_pct"    : round(len(df_labeled)/len(df_skus)*100, 2),
        "elapsed_sec"     : round(elapsed, 1),
    }
    with open(OUT_REPORT, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n💾 {OUT_CORPUS}  ({df_bal.shape})")
    print(f"💾 {OUT_REPORT}")

    print("\n📋 Muestra por etiqueta (post-fix):")
    for lid, lname in LABEL_NAMES.items():
        sub = df_bal[df_bal["label_id"] == lid].head(3)
        print(f"\n  [{lname}]")
        for _, r in sub.iterrows():
            print(f"    {str(r['title_repr'])[:75]}")
            print(f"    razón={r['razon']} | conf={r['confianza']} | trend={r['price_trend_pct']}% | used={r['pct_used']}")

    print("\n📊 Confianza post-fix:")
    print(df_bal.groupby("label")["confianza"].describe().round(3).to_string())

    print(f"\n✅ Corpus v4.1 listo en {elapsed:.1f}s")
    print("🔜 Siguiente: oe4_e5_embedder_v2.py apuntando a corpus_obsolescencia_v4.csv")

if __name__ == "__main__":
    main()
