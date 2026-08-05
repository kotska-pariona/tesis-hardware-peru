# =============================================================================
# e5_embedder.py — OE4: Generación de Embeddings con multilingual-E5-large
# Proyecto: HDS-ROI v4.0 | Universidad Nacional de Ingeniería
# Autor: Kotska Rony Pariona Martinez
# Fecha: 2026-07-30
#
# INPUT : data/corpus_obsolescencia.csv
# OUTPUT: data/embeddings_obsolescencia.npy   → matriz (N, 1024)
#         data/embeddings_meta.csv            → texto + label + label_id
#
# Modelo : intfloat/multilingual-e5-large (560M params, 1024-dim)
# Device : CUDA (RTX 3050 Ti) con batch_size=16
# Tiempo : ~30 segundos para 82 registros
# =============================================================================

import os
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

import torch
from sentence_transformers import SentenceTransformer

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# 0. CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

MODEL_NAME  = "intfloat/multilingual-e5-large"
DATA_DIR    = Path("data")
OUTPUT_DIR  = Path("data")

INPUT_FILE       = DATA_DIR  / "corpus_obsolescencia.csv"
OUTPUT_NPY       = OUTPUT_DIR / "embeddings_obsolescencia.npy"
OUTPUT_META      = OUTPUT_DIR / "embeddings_meta.csv"
OUTPUT_STATS     = OUTPUT_DIR / "embeddings_stats.txt"
LOG_FILE         = DATA_DIR  / "e5_embedder_log.txt"

# E5-large requiere prefijo 'query: ' para textos de búsqueda/clasificación
E5_PREFIX   = "query: "

# Batch size seguro para RTX 3050 Ti (4GB VRAM)
BATCH_SIZE  = 16

# ─────────────────────────────────────────────────────────────────────────────
# 1. UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_device() -> str:
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb  = torch.cuda.get_device_properties(0).total_memory / 1e9
        log(f"🎮 GPU detectada: {gpu_name} ({vram_gb:.1f} GB VRAM)")
        return "cuda"
    log("⚠️  CUDA no disponible. Usando CPU (más lento).")
    return "cpu"


# ─────────────────────────────────────────────────────────────────────────────
# 2. CARGA DEL CORPUS
# ─────────────────────────────────────────────────────────────────────────────

def load_corpus() -> pd.DataFrame:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"No se encontró {INPUT_FILE}\n"
            "Ejecuta primero: python corpus_builder.py"
        )

    df = pd.read_csv(INPUT_FILE, encoding="utf-8")
    log(f"📂 Corpus cargado: {len(df):,} registros | cols: {list(df.columns)}")

    # Validar columnas mínimas
    required = ["texto", "label", "label_id"]
    missing  = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Columnas faltantes en corpus: {missing}")

    # Limpiar textos nulos
    n_antes = len(df)
    df = df.dropna(subset=["texto"]).copy()
    df = df[df["texto"].str.strip() != ""].copy()
    if len(df) < n_antes:
        log(f"⚠️  Eliminados {n_antes - len(df)} registros con texto vacío")

    log(f"✅ Registros válidos: {len(df):,}")
    return df.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# 3. CARGA DEL MODELO E5-LARGE
# ─────────────────────────────────────────────────────────────────────────────

def load_model(device: str) -> SentenceTransformer:
    log(f"\n🤖 Cargando modelo: {MODEL_NAME}")
    log("   Primera vez: descarga ~2.2GB desde HuggingFace (~3-5 min)")
    log("   Siguiente vez: carga desde caché local (~10 seg)")

    t0 = datetime.now()
    model = SentenceTransformer(MODEL_NAME, device=device)
    elapsed = (datetime.now() - t0).total_seconds()

    # Info del modelo
    dim = model.get_sentence_embedding_dimension()
    log(f"✅ Modelo cargado en {elapsed:.1f}s")
    log(f"   Dimensión de embeddings : {dim}")
    log(f"   Device                  : {device.upper()}")
    log(f"   Max sequence length     : {model.max_seq_length}")

    return model


# ─────────────────────────────────────────────────────────────────────────────
# 4. GENERACIÓN DE EMBEDDINGS
# ─────────────────────────────────────────────────────────────────────────────

def generate_embeddings(model: SentenceTransformer,
                         texts: list[str],
                         device: str) -> np.ndarray:
    """
    Genera embeddings con E5-large.
    Aplica prefijo 'query: ' requerido por el modelo E5.
    """
    log(f"\n⚡ Generando embeddings para {len(texts):,} textos...")
    log(f"   Batch size : {BATCH_SIZE}")
    log(f"   Prefijo E5 : '{E5_PREFIX}'")

    # Aplicar prefijo E5 (OBLIGATORIO para multilingual-e5-large)
    prefixed_texts = [f"{E5_PREFIX}{t}" for t in texts]

    t0 = datetime.now()

    embeddings = model.encode(
        prefixed_texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,   # L2-norm → cosine sim = dot product
        show_progress_bar=True,
        device=device,
        convert_to_numpy=True,
    )

    elapsed = (datetime.now() - t0).total_seconds()

    log(f"\n✅ Embeddings generados en {elapsed:.1f}s")
    log(f"   Shape    : {embeddings.shape}")
    log(f"   Dtype    : {embeddings.dtype}")
    log(f"   Norma L2 (muestra): {np.linalg.norm(embeddings[0]):.4f}  ← debe ser ~1.0")

    return embeddings


# ─────────────────────────────────────────────────────────────────────────────
# 5. ANÁLISIS DE CALIDAD DE EMBEDDINGS
# ─────────────────────────────────────────────────────────────────────────────

def analyze_embeddings(embeddings: np.ndarray, df: pd.DataFrame):
    """
    Analiza la separabilidad de los embeddings por clase.
    Calcula distancia coseno inter-clase e intra-clase.
    """
    log("\n📐 Análisis de separabilidad por clase:")

    LABEL_MAP = {0: "VIGENTE", 1: "EN_RIESGO", 2: "OBSOLETO"}
    stats_lines = []

    # Centroides por clase
    centroids = {}
    for label_id, label_name in LABEL_MAP.items():
        mask = df["label_id"] == label_id
        if mask.sum() == 0:
            log(f"   ⚠️  Clase {label_name}: sin registros")
            continue
        centroid = embeddings[mask].mean(axis=0)
        centroid = centroid / np.linalg.norm(centroid)
        centroids[label_id] = centroid
        n = mask.sum()
        log(f"   {label_name:12s}: {n:>3} registros | centroide calculado")

    # Similitud intra-clase (cohesión)
    log("\n   📊 Cohesión intra-clase (sim coseno promedio con centroide):")
    for label_id, centroid in centroids.items():
        label_name = LABEL_MAP[label_id]
        mask = df["label_id"] == label_id
        embs = embeddings[mask]
        sims = embs @ centroid  # dot product = cosine (L2-norm)
        log(f"   {label_name:12s}: {sims.mean():.4f} ± {sims.std():.4f}")
        stats_lines.append(f"{label_name} cohesion: {sims.mean():.4f} ± {sims.std():.4f}")

    # Similitud inter-clase (separación)
    log("\n   📊 Separación inter-clase (sim coseno entre centroides):")
    label_ids = list(centroids.keys())
    for i in range(len(label_ids)):
        for j in range(i + 1, len(label_ids)):
            li, lj = label_ids[i], label_ids[j]
            sim = float(centroids[li] @ centroids[lj])
            log(f"   {LABEL_MAP[li]:12s} ↔ {LABEL_MAP[lj]:12s}: {sim:.4f}  "
                f"{'✅ bien separado' if sim < 0.85 else '⚠️  similar'}")
            stats_lines.append(f"{LABEL_MAP[li]} <-> {LABEL_MAP[lj]}: {sim:.4f}")

    # Guardar stats
    with open(OUTPUT_STATS, "w", encoding="utf-8") as f:
        f.write("EMBEDDINGS QUALITY STATS\n")
        f.write(f"Modelo: {MODEL_NAME}\n")
        f.write(f"Shape: {embeddings.shape}\n\n")
        f.write("\n".join(stats_lines))
    log(f"\n   Stats guardadas en: {OUTPUT_STATS}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. GUARDAR OUTPUTS
# ─────────────────────────────────────────────────────────────────────────────

def save_outputs(embeddings: np.ndarray, df: pd.DataFrame):
    # 6.1 Guardar matriz de embeddings
    np.save(OUTPUT_NPY, embeddings)
    size_mb = OUTPUT_NPY.stat().st_size / 1e6
    log(f"\n💾 Embeddings guardados: {OUTPUT_NPY}  ({size_mb:.1f} MB)")

    # 6.2 Guardar metadata con índice de vector
    meta_cols = ["texto", "label", "label_id", "confianza", "decision_src",
                 "keywords_match", "producto", "marca", "categoria",
                 "fuente", "precio_usd", "sku"]
    meta_cols_exist = [c for c in meta_cols if c in df.columns]

    meta = df[meta_cols_exist].copy()
    meta["vector_idx"] = range(len(meta))  # índice para lookup en .npy
    meta.to_csv(OUTPUT_META, index=False, encoding="utf-8")
    log(f"💾 Metadata guardada  : {OUTPUT_META}  ({len(meta):,} registros)")

    # 6.3 Verificación rápida
    loaded = np.load(OUTPUT_NPY)
    assert loaded.shape == embeddings.shape, "❌ Error en guardado/carga"
    log(f"✅ Verificación OK: shape {loaded.shape} cargado correctamente")


# ─────────────────────────────────────────────────────────────────────────────
# 7. MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    log("=" * 60)
    log("  e5_embedder.py — OE4 Embeddings E5-large")
    log(f"  Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)

    # Paso 1: Device
    device = get_device()

    # Paso 2: Corpus
    df = load_corpus()

    # Paso 3: Modelo
    model = load_model(device)

    # Paso 4: Embeddings
    embeddings = generate_embeddings(model, df["texto"].tolist(), device)

    # Paso 5: Análisis de calidad
    analyze_embeddings(embeddings, df)

    # Paso 6: Guardar
    save_outputs(embeddings, df)

    log("\n" + "=" * 60)
    log("✅ e5_embedder.py completado")
    log(f"   embeddings_obsolescencia.npy → {embeddings.shape}")
    log(f"   embeddings_meta.csv          → {len(df):,} registros")
    log("\n🔜 Siguiente paso: ejecutar classifier.py")
    log("=" * 60)


if __name__ == "__main__":
    main()