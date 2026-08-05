# =============================================================================
# corpus_builder.py v2 — OE4: Construcción de Corpus para Detección de Obsolescencia
# Proyecto: HDS-ROI v4.0 | Universidad Nacional de Ingeniería
# Fix v2: Columnas reales de precios_20260717_0313.csv
#         + Keywords ajustadas a productos reales coolbox_pe
#         + Conversión PEN → USD
#         + Parser de batch_id como fecha
# =============================================================================

import os
import re
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# 0. CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

DATA_DIR    = Path("data")
OUTPUT_DIR  = Path("data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = OUTPUT_DIR / "corpus_obsolescencia.csv"
LOG_FILE    = OUTPUT_DIR / "corpus_builder_log.txt"

# Tipo de cambio PEN → USD (actualizar si es necesario)
TC_PEN_USD = 3.75

# Columnas reales del CSV coolbox_pe
COL_MAP = {
    "producto":   ["name", "producto", "nombre", "title"],
    "precio":     ["price_pen", "precio_usd", "precio", "price"],
    "precio_orig":["price_orig_pen", "precio_original", "price_orig"],
    "fuente":     ["source", "fuente", "tienda", "store"],
    "disponible": ["available_qty", "disponible", "available", "stock"],
    "descuento":  ["discount_pct", "descuento_pct", "descuento", "discount"],
    "fecha":      ["batch_id", "fecha", "fecha_scraping", "date", "timestamp"],
    "categoria":  ["category", "categoria", "tipo", "type"],
    "marca":      ["brand", "marca"],
    "sku":        ["sku", "product_id", "id"],
    "url":        ["url", "link"],
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. REGLAS DE WEAK SUPERVISION — Ajustadas a datos reales coolbox_pe
# ─────────────────────────────────────────────────────────────────────────────

# ── OBSOLETO: generaciones claramente superadas ───────────────────────────────
KEYWORDS_OBSOLETO = [
    # CPUs Intel legacy
    "i3-10", "i5-10", "i7-10", "i9-10",          # Gen 10 (LGA1200)
    "i3-11", "i5-11", "i7-11", "i9-11",          # Gen 11 (LGA1200)
    "i3-12", "i5-12", "i7-12", "i9-12",          # Gen 12 (Alder Lake)
    "lga1200", "lga1151",                          # Sockets obsoletos Intel
    # CPUs AMD legacy
    "ryzen 3 3", "ryzen 5 3", "ryzen 7 3",        # Ryzen 3000 (Zen 2)
    "ryzen 3 4", "ryzen 5 4", "ryzen 7 4",        # Ryzen 4000 (Zen 3 mobile)
    "ryzen 5 5600g", "ryzen 5 5600x",             # Ryzen 5000 AM4 (superado)
    "ryzen 7 5700", "ryzen 9 5900", "ryzen 9 5950",
    "am4",                                         # Socket AM4 (superado por AM5)
    # GPUs legacy
    "rtx 2060", "rtx 2070", "rtx 2080",          # RTX 20xx
    "rtx 3060", "rtx 3070", "rtx 3080", "rtx 3090", # RTX 30xx
    "gtx 1650", "gtx 1660",                       # GTX legacy
    "rx 6600", "rx 6700", "rx 6800", "rx 6900",  # RX 6000
    # RAM legacy
    "ddr3", "ddr4",                               # DDR4 en transición a DDR5
    # Almacenamiento legacy
    "sata ssd", "hdd", "disco duro",
    # Señales explícitas
    "descontinuado", "fin de vida", "legacy",
    "última unidad", "ultimas unidades", "agotado",
    "reemplazado", "modelo anterior", "gen anterior",
]

# ── EN_RIESGO: generaciones en transición activa ──────────────────────────────
KEYWORDS_EN_RIESGO = [
    # CPUs Intel en transición
    "i3-13", "i5-13", "i7-13", "i9-13",          # Gen 13 (Raptor Lake)
    "i3-14", "i5-14", "i7-14", "i9-14",          # Gen 14 (Raptor Lake Refresh)
    "lga1700",                                     # Socket en transición
    # CPUs AMD en transición
    "ryzen 5 7600", "ryzen 7 7700", "ryzen 9 7900", "ryzen 9 7950",
    "ryzen 5 8600", "ryzen 7 8700",               # Ryzen 7000/8000 (AM5 gen1)
    # GPUs en transición
    "rtx 4060", "rtx 4070", "rtx 4080", "rtx 4090", # RTX 40xx (cuando 50xx domina)
    "rx 7600", "rx 7700", "rx 7800", "rx 7900",  # RX 7000
    # Señales de mercado
    "próximo lanzamiento", "proximo lanzamiento",
    "nueva generación", "nueva generacion",
    "sucesor anunciado", "stock limitado",
    "pocas unidades", "liquidación", "liquidacion",
    "precio bajando", "clearance",
]

# ── VIGENTE: generaciones actuales (2025-2026) ────────────────────────────────
KEYWORDS_VIGENTE = [
    # CPUs Intel actuales
    "core ultra",                                  # Intel Core Ultra (Arrow Lake)
    "lga1851",                                     # Socket actual Intel
    "ultra 5", "ultra 7", "ultra 9",
    # CPUs AMD actuales
    "ryzen 9 9950", "ryzen 9 9900",
    "ryzen 7 9700", "ryzen 5 9600",               # Ryzen 9000 (Zen 5)
    "am5",                                         # Socket actual AMD
    # GPUs actuales
    "rtx 5060", "rtx 5070", "rtx 5080", "rtx 5090", # RTX 50xx
    "rx 8000", "rx 9000",                         # RX 8000/9000
    # RAM actual
    "ddr5", "lpddr5",
    # Almacenamiento actual
    "nvme gen5", "pcie 5.0", "gen5",
    # Señales temporales
    "2025", "2026",
    "nuevo", "nueva", "latest",
    "disponible", "en stock",
]

# Umbrales numéricos
DESCUENTO_OBSOLETO = 0.30   # > 30% → señal obsolescencia
DESCUENTO_RIESGO   = 0.15   # 15-30% → en riesgo
PRECIO_CAIDA_PCT   = 0.10   # Caída > 10% vs precio original → en riesgo

# ─────────────────────────────────────────────────────────────────────────────
# 2. FUNCIONES AUXILIARES
# ─────────────────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def normalize_col(df: pd.DataFrame, col_type: str) -> str | None:
    for candidate in COL_MAP.get(col_type, []):
        if candidate in df.columns:
            return candidate
    return None


def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s\.\-\/]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def parse_fecha(batch_id: str) -> str:
    """
    Convierte batch_id '20260717_0313' → '2026-07-17 03:13:00'
    """
    try:
        dt = datetime.strptime(str(batch_id), "%Y%m%d_%H%M")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(batch_id)


def apply_lexical_rules(text: str) -> tuple[str, float]:
    text_clean = clean_text(text)

    score_obsoleto  = 0
    score_en_riesgo = 0
    score_vigente   = 0

    matched_obs, matched_risk, matched_vig = [], [], []

    for kw in KEYWORDS_OBSOLETO:
        if kw in text_clean:
            score_obsoleto += 1
            matched_obs.append(kw)

    for kw in KEYWORDS_EN_RIESGO:
        if kw in text_clean:
            score_en_riesgo += 1
            matched_risk.append(kw)

    for kw in KEYWORDS_VIGENTE:
        if kw in text_clean:
            score_vigente += 1
            matched_vig.append(kw)

    total = score_obsoleto + score_en_riesgo + score_vigente

    if total == 0:
        return "DESCONOCIDO", 0.0, []

    scores = {
        "OBSOLETO":  score_obsoleto,
        "EN_RIESGO": score_en_riesgo,
        "VIGENTE":   score_vigente,
    }
    label = max(scores, key=scores.get)
    confianza = scores[label] / total

    matched = {"OBSOLETO": matched_obs,
               "EN_RIESGO": matched_risk,
               "VIGENTE": matched_vig}[label]

    return label, round(confianza, 3), matched


def apply_numeric_rules(row: pd.Series,
                         col_precio: str,
                         col_precio_orig: str,
                         col_descuento: str) -> tuple[str, float]:
    label, confianza = "DESCONOCIDO", 0.0

    # Señal de descuento
    if col_descuento and col_descuento in row.index:
        desc = row[col_descuento]
        if pd.notna(desc) and float(desc) > 0:
            desc = float(desc)
            if desc >= DESCUENTO_OBSOLETO:
                label, confianza = "OBSOLETO", 0.72
            elif desc >= DESCUENTO_RIESGO:
                label, confianza = "EN_RIESGO", 0.62

    # Señal de caída de precio vs original
    if col_precio and col_precio_orig:
        if col_precio in row.index and col_precio_orig in row.index:
            p_act  = row[col_precio]
            p_orig = row[col_precio_orig]
            if pd.notna(p_act) and pd.notna(p_orig) and float(p_orig) > 0:
                caida = (float(p_orig) - float(p_act)) / float(p_orig)
                if caida >= PRECIO_CAIDA_PCT:
                    label, confianza = "EN_RIESGO", max(confianza, 0.58)

    return label, confianza


def consensus_label(lex_label, lex_conf, num_label, num_conf):
    if lex_label == "DESCONOCIDO" and num_label == "DESCONOCIDO":
        return "VIGENTE", 0.40, "default"
    if lex_label == "DESCONOCIDO":
        return num_label, num_conf, "numeric"
    if num_label == "DESCONOCIDO":
        return lex_label, lex_conf, "lexical"
    if lex_label == num_label:
        conf = min(1.0, (lex_conf + num_conf) / 2 + 0.10)
        return lex_label, round(conf, 3), "consensus"
    if lex_conf >= num_conf:
        return lex_label, lex_conf, "lexical_wins"
    return num_label, num_conf, "numeric_wins"


# ─────────────────────────────────────────────────────────────────────────────
# 3. CARGA DE CSVs
# ─────────────────────────────────────────────────────────────────────────────

def load_all_csvs() -> pd.DataFrame:
    csv_files = list(DATA_DIR.glob("precios_*.csv"))

    if not csv_files:
        raise FileNotFoundError(
            "No se encontraron archivos precios_*.csv en data/\n"
            "Asegúrate de tener tus CSVs en la carpeta data/"
        )

    log(f"📂 Archivos encontrados: {len(csv_files)}")
    frames = []

    for fpath in csv_files:
        try:
            df = pd.read_csv(fpath, encoding="utf-8")
            df["_source_file"] = fpath.name
            frames.append(df)
            log(f"   ✅ {fpath.name:45s} → {len(df):>5,} registros")
        except Exception as e:
            log(f"   ❌ {fpath.name} → Error: {e}")

    combined = pd.concat(frames, ignore_index=True)
    log(f"\n📊 Total combinado: {len(combined):,} registros de {len(frames)} archivo(s)")
    return combined


# ─────────────────────────────────────────────────────────────────────────────
# 4. CONSTRUCCIÓN DEL CORPUS
# ─────────────────────────────────────────────────────────────────────────────

def build_corpus(df: pd.DataFrame) -> pd.DataFrame:
    log("\n🔧 Iniciando construcción del corpus...")

    # Detectar columnas
    col_producto    = normalize_col(df, "producto")
    col_precio      = normalize_col(df, "precio")
    col_precio_orig = normalize_col(df, "precio_orig")
    col_fuente      = normalize_col(df, "fuente")
    col_disponible  = normalize_col(df, "disponible")
    col_descuento   = normalize_col(df, "descuento")
    col_fecha       = normalize_col(df, "fecha")
    col_categoria   = normalize_col(df, "categoria")
    col_marca       = normalize_col(df, "marca")
    col_sku         = normalize_col(df, "sku")
    col_url         = normalize_col(df, "url")

    log(f"   producto    : {col_producto}")
    log(f"   precio      : {col_precio}  (PEN → se convertirá a USD ÷{TC_PEN_USD})")
    log(f"   precio_orig : {col_precio_orig}")
    log(f"   fuente      : {col_fuente}")
    log(f"   disponible  : {col_disponible}")
    log(f"   descuento   : {col_descuento}")
    log(f"   fecha       : {col_fecha}  (batch_id → parseado)")
    log(f"   categoria   : {col_categoria}")
    log(f"   marca       : {col_marca}")

    if col_producto is None:
        raise ValueError(f"No se encontró columna de producto. Cols: {list(df.columns)}")

    # Convertir precio PEN → USD
    if col_precio:
        df["precio_usd"] = (df[col_precio] / TC_PEN_USD).round(2)
    if col_precio_orig:
        df["precio_orig_usd"] = (df[col_precio_orig] / TC_PEN_USD).round(2)

    # Parsear fecha desde batch_id
    if col_fecha:
        df["fecha_parsed"] = df[col_fecha].apply(parse_fecha)

    # ── Construir texto enriquecido ──────────────────────────────────────────
    def build_text(row):
        parts = []
        if col_producto and pd.notna(row.get(col_producto, "")):
            parts.append(str(row[col_producto]))
        if col_marca and pd.notna(row.get(col_marca, "")):
            parts.append(f"marca: {row[col_marca]}")
        if col_categoria and pd.notna(row.get(col_categoria, "")):
            parts.append(f"categoria: {row[col_categoria]}")
        if col_fuente and pd.notna(row.get(col_fuente, "")):
            parts.append(f"fuente: {row[col_fuente]}")
        if "precio_usd" in row.index and pd.notna(row.get("precio_usd")):
            parts.append(f"precio: {row['precio_usd']} USD")
        if col_descuento and pd.notna(row.get(col_descuento, 0)):
            desc_val = float(row[col_descuento])
            if desc_val > 0:
                parts.append(f"descuento: {desc_val:.0%}")
        return " | ".join(parts)

    df["texto_enriquecido"] = df.apply(build_text, axis=1)

    # ── Aplicar Weak Supervision ─────────────────────────────────────────────
    log("🏷️  Aplicando Weak Supervision...")

    resultados = []
    for idx, row in df.iterrows():
        texto = row["texto_enriquecido"]

        lex_label, lex_conf, matched_kws = apply_lexical_rules(texto)
        num_label, num_conf = apply_numeric_rules(
            row, "precio_usd", "precio_orig_usd", col_descuento
        )
        final_label, final_conf, decision_src = consensus_label(
            lex_label, lex_conf, num_label, num_conf
        )

        resultados.append({
            "label_lexico":    lex_label,
            "conf_lexico":     lex_conf,
            "keywords_match":  ", ".join(matched_kws) if matched_kws else "",
            "label_numerico":  num_label,
            "conf_numerico":   num_conf,
            "label":           final_label,
            "confianza":       final_conf,
            "decision_src":    decision_src,
        })

    df_labels = pd.DataFrame(resultados)
    df = pd.concat([df.reset_index(drop=True), df_labels], axis=1)

    # ── Corpus final ─────────────────────────────────────────────────────────
    corpus = pd.DataFrame()
    corpus["texto"]           = df["texto_enriquecido"]
    corpus["label"]           = df["label"]
    corpus["confianza"]       = df["confianza"]
    corpus["decision_src"]    = df["decision_src"]
    corpus["keywords_match"]  = df["keywords_match"]
    corpus["label_lexico"]    = df["label_lexico"]
    corpus["label_numerico"]  = df["label_numerico"]

    # Columnas de negocio
    for col_name, col_real in [
        ("producto",    col_producto),
        ("marca",       col_marca),
        ("categoria",   col_categoria),
        ("fuente",      col_fuente),
        ("precio_usd",  "precio_usd"),
        ("descuento",   col_descuento),
        ("fecha",       "fecha_parsed"),
        ("sku",         col_sku),
        ("url",         col_url),
    ]:
        if col_real and col_real in df.columns:
            corpus[col_name] = df[col_real].values
        else:
            corpus[col_name] = None

    corpus["source_file"] = df["_source_file"]

    # ── Filtro de confianza ──────────────────────────────────────────────────
    CONFIANZA_MINIMA = 0.40
    n_antes = len(corpus)
    corpus = corpus[corpus["confianza"] >= CONFIANZA_MINIMA].copy()
    corpus = corpus.drop_duplicates(subset=["texto"]).copy()
    log(f"   Antes filtro : {n_antes:,} | Después: {len(corpus):,}")

    # ── Label encoding ───────────────────────────────────────────────────────
    LABEL_MAP = {"VIGENTE": 0, "EN_RIESGO": 1, "OBSOLETO": 2}
    corpus["label_id"] = corpus["label"].map(LABEL_MAP)

    return corpus


# ─────────────────────────────────────────────────────────────────────────────
# 5. ESTADÍSTICAS
# ─────────────────────────────────────────────────────────────────────────────

def print_stats(corpus: pd.DataFrame):
    log("\n" + "="*60)
    log("📊 ESTADÍSTICAS DEL CORPUS")
    log("="*60)
    log(f"Total registros       : {len(corpus):,}")
    log(f"Confianza promedio    : {corpus['confianza'].mean():.3f}")
    log(f"Confianza mediana     : {corpus['confianza'].median():.3f}")

    log("\n📌 Distribución de Labels:")
    dist = corpus["label"].value_counts()
    for label, count in dist.items():
        pct = count / len(corpus) * 100
        bar = "█" * int(pct / 2)
        log(f"   {label:12s}: {count:>4} ({pct:5.1f}%) {bar}")

    log("\n📌 Keywords que activaron cada label:")
    for label in ["OBSOLETO", "EN_RIESGO", "VIGENTE"]:
        sub = corpus[corpus["label"] == label]["keywords_match"]
        kws = [k for s in sub if isinstance(s, str) for k in s.split(", ") if k]
        from collections import Counter
        top = Counter(kws).most_common(5)
        log(f"   {label}: {top}")

    log("\n📌 Distribución por Categoría:")
    if "categoria" in corpus.columns:
        for cat, grp in corpus.groupby("categoria")["label"].value_counts().items():
            log(f"   {str(cat[0]):12s} | {cat[1]:12s}: {grp}")

    log("\n📌 Fuente de Decisión:")
    for src, count in corpus["decision_src"].value_counts().items():
        log(f"   {src:20s}: {count}")

    dist_pct = corpus["label"].value_counts(normalize=True)
    if dist_pct.max() > 0.70:
        log(f"\n⚠️  DESBALANCE: '{dist_pct.idxmax()}' domina con {dist_pct.max():.0%}")
        log("   → Se usará class_weight='balanced' en el clasificador")

    if "EN_RIESGO" not in dist.index:
        log("\n⚠️  CLASE EN_RIESGO AUSENTE")
        log("   → Necesitas más fuentes (Falabella, Hiraoka, Amazon)")
        log("   → O scraping de más fechas para detectar variación de precios")

    log("="*60)


# ─────────────────────────────────────────────────────────────────────────────
# 6. MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    log("="*60)
    log("  corpus_builder.py v2 — OE4 Detección de Obsolescencia")
    log(f"  Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("="*60)

    df_raw  = load_all_csvs()
    corpus  = build_corpus(df_raw)
    print_stats(corpus)

    corpus.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
    log(f"\n✅ Corpus guardado en: {OUTPUT_FILE}")
    log(f"   Shape   : {corpus.shape}")
    log(f"   Columnas: {list(corpus.columns)}")
    log(f"\n🔜 Siguiente paso: ejecutar e5_embedder.py")


if __name__ == "__main__":
    main()