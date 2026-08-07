"""
OE4 — corpus_builder_v3.py
Extrae muestra estratificada del MASTER_hardware_peru.csv
y genera corpus balanceado para E5-large.
META: ~3,000 registros | 3 clases equilibradas
"""
import re, json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
MASTER      = Path("data/raw/MASTER_hardware_peru.csv")
OUT_DIR     = Path("data")
OUT_CORPUS  = OUT_DIR / "corpus_obsolescencia_v3.csv"
OUT_REPORT  = OUT_DIR / "corpus_v3_report.json"
RANDOM_SEED = 42
N_PER_CLASS = 1000   # 1000 × 3 clases = 3000 registros

LABEL_NAMES = {0: "VIGENTE", 1: "EN_RIESGO", 2: "OBSOLETO"}

# ── REGLAS LÉXICAS ────────────────────────────────────────────────────────────
RULES = {
    2: [  # OBSOLETO
        r'\bddr[12]\b', r'\bpc[23]\b',
        r'\bgtx\s*[4-9]\d{2}\b', r'\bgtx\s*10[0-9]{2}\b',
        r'\brtx\s*20[0-9]{2}\b',
        r'\brx\s*[45][0-9]{2}\b',
        r'\bi[357]-[2-7]\d{3}\w*\b',
        r'\bryzen\s*[123]\s*[123][0-9]{3}\b',
        r'\blga\s*(1151|1150|1155|1156|775|1366|2011)\b',
        r'\bam[23]\+?\b', r'\bfm[12]\b',
        r'\bwindows\s*(7|8|xp|vista)\b',
        r'\bddr3\b',
        r'\brefurbish\w*\b', r'\breacondicion\w*\b',
        r'\busado\b', r'\bused\b',
        r'\bi[357]-[89]\d{3}\w*\b',
        r'\bryzen\s*[357]\s*[2-4][0-9]{3}\b',
    ],
    1: [  # EN_RIESGO
        r'\bddr4\b',
        r'\bgtx\s*16[0-9]{2}\b',
        r'\brtx\s*30[0-9]{2}\b',
        r'\brtx\s*40[0-9]{2}\b',
        r'\brx\s*6[0-9]{3}\b',
        r'\brx\s*7[0-9]{3}\b',
        r'\bi[357]-1[012][0-9]{3}\w*\b',
        r'\bryzen\s*[57]\s*5[0-9]{3}\b',
        r'\blga\s*1700\b',
        r'\bam4\b',
        r'\bpcie\s*[34]\.0\b',
        r'\bnvme\b(?!.*pcie\s*5)',
        r'\bi[357]-13[0-9]{3}\w*\b',
        r'\bi[357]-14[0-9]{3}\w*\b',
        r'\bryzen\s*[57]\s*7[0-9]{3}\b',
    ],
    0: [  # VIGENTE
        r'\bddr5\b',
        r'\brtx\s*50[0-9]{2}\b',
        r'\brx\s*9[0-9]{3}\b',
        r'\bcore\s*ultra\b',
        r'\bryzen\s*[579]\s*9[0-9]{3}\b',
        r'\blga\s*1851\b',
        r'\bam5\b',
        r'\bpcie\s*5\.0\b',
        r'\brtx\s*[56][0-9]{3}\b',
        r'\bwindows\s*11\b',
        r'\bi[357]-2[0-9]{4}\w*\b',
        r'\bryzen\s*[579]\s*8[0-9]{3}\b',
        r'\bgen\s*[56]\b',
    ],
}

def label_title(title: str):
    t = str(title).lower()
    scores = {0: 0, 1: 0, 2: 0}
    for lbl, patterns in RULES.items():
        for p in patterns:
            if re.search(p, t):
                scores[lbl] += 1
    best_lbl = max(scores, key=scores.get)
    best_score = scores[best_lbl]
    if best_score == 0:
        return -1, 0.0   # sin etiqueta
    # Confianza: matches / total_patterns_de_esa_clase
    conf = min(best_score / 3.0, 1.0)
    return best_lbl, round(conf, 3)

def build_texto(row):
    parts = [str(row.get("title", "")).strip()]
    if pd.notna(row.get("brand")):
        parts.append(f"marca: {str(row['brand']).lower().strip()}")
    if pd.notna(row.get("category")):
        parts.append(f"categoria: {str(row['category']).upper().strip()}")
    if pd.notna(row.get("source")):
        parts.append(f"fuente: {str(row['source']).strip()}")
    if pd.notna(row.get("price_usd")) and float(row.get("price_usd", 0)) > 0:
        parts.append(f"precio: {float(row['price_usd']):.1f} USD")
    return " | ".join(p for p in parts if p.strip())

def main():
    t0 = datetime.now()
    print("=" * 60)
    print("  OE4 corpus_builder_v3.py")
    print(f"  Inicio: {t0.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ── Cargar MASTER en chunks para no saturar RAM ───────────────────────
    print(f"\n📂 Cargando {MASTER} en chunks...")
    COLS = ["title", "brand", "category", "source",
            "price_usd", "discount_pct", "condition", "sku"]
    chunks = []
    chunk_size = 50_000
    for i, chunk in enumerate(pd.read_csv(
            MASTER, usecols=lambda c: c in COLS,
            low_memory=False, chunksize=chunk_size)):
        chunks.append(chunk)
        print(f"  chunk {i+1}: {len(chunk):,} filas", end="\r")
    df = pd.concat(chunks, ignore_index=True)
    print(f"\n  Total cargado: {len(df):,} filas | cols: {list(df.columns)}")

    # ── Limpiar ───────────────────────────────────────────────────────────
    df = df.dropna(subset=["title"]).copy()
    df["title"] = df["title"].astype(str).str.strip()
    df = df[df["title"].str.len() > 5].copy()
    print(f"  Tras limpieza: {len(df):,} filas")

    # ── Etiquetar ─────────────────────────────────────────────────────────
    print("\n🏷️  Aplicando reglas léxicas...")
    results   = df["title"].apply(label_title)
    df["label_id"]   = results.apply(lambda x: x[0])
    df["confianza"]  = results.apply(lambda x: x[1])
    df["label"]      = df["label_id"].map(LABEL_NAMES)

    df_labeled = df[df["label_id"] >= 0].copy()
    print(f"  Etiquetados: {len(df_labeled):,} / {len(df):,}")
    print(f"  Distribución bruta:")
    for lbl_id, lbl_name in LABEL_NAMES.items():
        n = (df_labeled["label_id"] == lbl_id).sum()
        print(f"    {lbl_name:12s}: {n:>6,}")

    # ── Muestreo estratificado balanceado ─────────────────────────────────
    print(f"\n⚖️  Muestreo estratificado ({N_PER_CLASS} por clase)...")
    parts = []
    actual_counts = {}
    for lbl_id, lbl_name in LABEL_NAMES.items():
        sub = df_labeled[df_labeled["label_id"] == lbl_id]
        # Priorizar alta confianza
        sub_sorted = sub.sort_values("confianza", ascending=False)
        n = min(N_PER_CLASS, len(sub_sorted))
        actual_counts[lbl_name] = n
        parts.append(sub_sorted.head(n))
        print(f"    {lbl_name:12s}: {n:>5,} seleccionados")

    df_balanced = pd.concat(parts, ignore_index=True)
    df_balanced = df_balanced.sample(frac=1, random_state=RANDOM_SEED).reset_index(drop=True)

    # ── Construir texto E5 ────────────────────────────────────────────────
    print("\n📝 Construyendo texto enriquecido para E5-large...")
    df_balanced["texto"] = df_balanced.apply(build_texto, axis=1)

    # ── Guardar ───────────────────────────────────────────────────────────
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cols_out = ["texto", "label", "label_id", "confianza",
                "title", "brand", "category", "source",
                "price_usd", "sku"]
    cols_out = [c for c in cols_out if c in df_balanced.columns]
    df_balanced[cols_out].to_csv(OUT_CORPUS, index=False, encoding="utf-8")
    print(f"\n💾 Corpus guardado: {OUT_CORPUS}")
    print(f"   Shape: {df_balanced.shape}")

    # ── Reporte ───────────────────────────────────────────────────────────
    elapsed = (datetime.now() - t0).total_seconds()
    report = {
        "version"        : "v3",
        "timestamp"      : datetime.now().isoformat(),
        "master_rows"    : len(df),
        "labeled_rows"   : len(df_labeled),
        "corpus_rows"    : len(df_balanced),
        "n_per_class_target": N_PER_CLASS,
        "actual_counts"  : actual_counts,
        "coverage_pct"   : round(len(df_labeled)/len(df)*100, 2),
        "elapsed_sec"    : round(elapsed, 1),
    }
    with open(OUT_REPORT, "w") as f:
        json.dump(report, f, indent=2)
    print(f"💾 Reporte: {OUT_REPORT}")

    print("\n" + "=" * 60)
    print(f"✅ Corpus v3 listo: {len(df_balanced):,} registros")
    print(f"   Tiempo: {elapsed:.1f}s")
    print(f"🔜 Siguiente: python e5_embedder_v2.py")
    print("=" * 60)

if __name__ == "__main__":
    main()
