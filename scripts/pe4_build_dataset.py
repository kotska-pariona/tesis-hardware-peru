"""
PE4 — Build Dataset: Etiquetado por reglas heurísticas sobre títulos.
Genera:
  - pe4_labeled.parquet              (dataset completo con label)
  - pe4_labeled_bert_ready.csv       (solo etiquetados, input BERT)
  - pe4_labeled_validation_sample.csv(150 muestras para revisión manual)
  - pe4_label_report.json            (estadísticas de cobertura)
"""
import argparse, json, re
import pandas as pd
from pathlib import Path

# ── Normalización de categorías (60 → 15) ────────────────────────────────────
CAT_MAP = {
    "ram":"ram","RAM":"ram","memorias_ram":"ram","memory":"ram",
    "gpu":"gpu","GPU":"gpu","tarjetas_video":"gpu","graphics_card":"gpu","vga":"gpu",
    "cpu":"cpu","CPU":"cpu","procesador":"cpu","processor":"cpu",
    "motherboard":"motherboard","placa_madre":"motherboard","mainboard":"motherboard",
    "ssd":"storage","hdd":"storage","storage":"storage","disco_duro":"storage","nvme":"storage",
    "laptop":"laptop","notebook":"laptop","portatil":"laptop",
    "desktop":"desktop","pc":"desktop","computadora":"desktop","all_in_one":"desktop",
    "monitor":"monitor","monitores":"monitor","display":"monitor",
    "psu":"psu","fuente":"psu","power_supply":"psu",
    "case":"case","gabinete":"case","chasis":"case",
    "cooler":"cooler","cooling":"cooler","refrigeracion":"cooler",
    "peripheral":"peripheral","periferico":"peripheral","keyboard":"peripheral",
    "mouse":"peripheral","headset":"peripheral","webcam":"peripheral",
    "network":"network","networking":"network","router":"network","wifi":"network",
    "ups":"ups","estabilizador":"ups",
}

# ── Reglas de obsolescencia (regex sobre título en minúsculas) ────────────────
RULES = {
    2: [  # OBSOLETO
        r'\brefurbish\w*\b', r'\breacondicion\w*\b', r'\bdiscontinu\w*\b',
        r'\blegacy\b', r'\bused\b', r'\busado\b',
        r'\bddr[12]\b', r'\bpc[23]\b',
        r'\bgtx\s*[4-9]\d{2}\b', r'\bgtx\s*10[0-9]{2}\b',
        r'\brtx\s*20[0-9]{2}\b',
        r'\brx\s*[45][0-9]{2}\b',
        r'\bcore\s*[2i][357]\s*[2-7]\d{3}\b',
        r'\bi[357]-[2-7]\d{3}\w*\b',
        r'\bryzen\s*[123]\s*[123][0-9]{3}\b',
        r'\blga\s*(1151|1150|1155|1156|775|1366|2011)\b',
        r'\bam[23]\+?\b', r'\bfm[12]\b',
        r'\bwindows\s*(7|8|xp|vista)\b',
        r'\bddr3\b',
    ],
    1: [  # TRANSICIÓN
        r'\bddr4\b',
        r'\bgtx\s*16[0-9]{2}\b',
        r'\brtx\s*30[0-9]{2}\b', r'\brtx\s*40[0-9]{2}\b',
        r'\brx\s*6[0-9]{3}\b', r'\brx\s*7[0-9]{3}\b',
        r'\bi[357]-1[012][0-9]{3}\w*\b',
        r'\bryzen\s*[57]\s*5[0-9]{3}\b',
        r'\blga\s*1700\b',
        r'\bam4\b',
        r'\bpcie\s*[34]\.0\b', r'\bpci-e\s*[34]\.0\b',
        r'\bnvme\b', r'\bm\.2\b',
    ],
    0: [  # VIGENTE
        r'\bddr5\b',
        r'\brtx\s*50[0-9]{2}\b',
        r'\brx\s*9[0-9]{3}\b',
        r'\bcore\s*ultra\b',
        r'\bryzen\s*[579]\s*9[0-9]{3}\b',
        r'\blga\s*1851\b',
        r'\bam5\b',
        r'\bpcie\s*5\.0\b', r'\bpci-e\s*5\.0\b',
        r'\bnew\b', r'\bnuevo\b', r'\blatest\b',
        r'\bgen\s*5\b',
        r'\bwindows\s*11\b',
        r'\brtx\s*[56][0-9]{3}\b',
    ],
}

def normalize_category(cat):
    if pd.isna(cat): return "unknown"
    cat_str = str(cat).strip()
    # Si parece URL, precio o ASIN → descartar
    if re.search(r'(https?://|www\.|^\d+\.?\d*$|^B0[A-Z0-9]{8}$)', cat_str):
        return "unknown"
    return CAT_MAP.get(cat_str, cat_str.lower()[:20])

def label_title(title: str):
    """Retorna (label, confidence, matched_rule)"""
    t = str(title).lower()
    for lbl in [2, 1, 0]:
        for pattern in RULES[lbl]:
            if re.search(pattern, t):
                # Confianza: si hay múltiples matches → high
                matches = sum(1 for p in RULES[lbl] if re.search(p, t))
                conf = "high" if matches >= 2 else "medium"
                return lbl, conf, pattern
    return -1, "none", ""

def main(input_path, output_dir, report_path):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Cargando {input_path} ...")
    df = pd.read_csv(input_path, low_memory=False)
    print(f"  Shape original: {df.shape}")

    # Limpiar columnas clave
    df["title_clean"]    = df["title"].fillna("").astype(str).str.strip()
    df["category_clean"] = df["category"].apply(normalize_category)
    df["brand_clean"]    = df.get("brand", pd.Series(["unknown"]*len(df))).fillna("unknown").astype(str).str.strip().str.lower()

    # Etiquetado
    print("  Aplicando reglas heurísticas ...")
    results = df["title_clean"].apply(label_title)
    df["label"]        = results.apply(lambda x: x[0])
    df["confidence"]   = results.apply(lambda x: x[1])
    df["matched_rule"] = results.apply(lambda x: x[2])

    # Input BERT
    df["bert_input"] = (
        df["title_clean"] + " [SEP] " +
        df["category_clean"] + " [SEP] " +
        df["brand_clean"]
    )

    # Guardar dataset completo
    parquet_path = output_dir / "pe4_labeled.parquet"
    df.to_parquet(parquet_path, index=False)
    print(f"  Guardado: {parquet_path}")

    # Dataset BERT (solo etiquetados, label >= 0)
    df_bert = df[df["label"] >= 0][["bert_input","label","confidence","title_clean","category_clean","brand_clean"]].copy()
    bert_path = output_dir / "pe4_labeled_bert_ready.csv"
    df_bert.to_csv(bert_path, index=False)
    print(f"  Guardado: {bert_path}  ({len(df_bert):,} filas etiquetadas)")

    # Muestra de validación manual (50 × 3 clases)
    samples = []
    for lbl in [0, 1, 2]:
        sub = df_bert[df_bert["label"] == lbl]
        n   = min(50, len(sub))
        samples.append(sub.sample(n, random_state=42))
    val_df = pd.concat(samples).sample(frac=1, random_state=42)
    val_path = output_dir / "pe4_labeled_validation_sample.csv"
    val_df.to_csv(val_path, index=False)
    print(f"  Guardado: {val_path}  ({len(val_df)} muestras para revisión manual)")

    # Reporte
    total       = len(df)
    labeled     = len(df_bert)
    dist        = df_bert["label"].value_counts().to_dict()
    conf_dist   = df_bert["confidence"].value_counts().to_dict()
    report = {
        "total_rows":      total,
        "labeled_rows":    labeled,
        "unlabeled_rows":  total - labeled,
        "coverage_pct":    round(labeled / total * 100, 2),
        "label_distribution": {
            "0_vigente":    int(dist.get(0, 0)),
            "1_transicion": int(dist.get(1, 0)),
            "2_obsoleto":   int(dist.get(2, 0)),
        },
        "confidence_distribution": {k: int(v) for k,v in conf_dist.items()},
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Guardado: {report_path}")
    print("\n  ── REPORTE ──────────────────────────────────")
    print(f"  Total filas:     {total:>10,}")
    print(f"  Etiquetadas:     {labeled:>10,}  ({report['coverage_pct']}%)")
    print(f"  Sin etiquetar:   {total-labeled:>10,}")
    print(f"  Vigente  (0):    {dist.get(0,0):>10,}")
    print(f"  Transición (1):  {dist.get(1,0):>10,}")
    print(f"  Obsoleto (2):    {dist.get(2,0):>10,}")
    print("  ─────────────────────────────────────────────")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default="data/raw/MASTER_hardware_peru.csv")
    parser.add_argument("--output", default="data/processed")
    parser.add_argument("--report", default="data/processed/pe4_label_report.json")
    args = parser.parse_args()
    main(args.input, args.output, args.report)
