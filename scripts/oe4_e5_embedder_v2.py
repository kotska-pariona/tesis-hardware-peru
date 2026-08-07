"""
OE4 — e5_embedder_v2.py
Genera embeddings E5-large para corpus_obsolescencia_v4.csv
INPUT : data/corpus_obsolescencia_v4.csv
OUTPUT: data/embeddings_v4.npy  (3000, 1024)
        data/embeddings_v4_meta.csv
"""
import numpy as np
import pandas as pd
import torch
from pathlib import Path
from datetime import datetime
from sentence_transformers import SentenceTransformer

CORPUS    = Path("data/corpus_obsolescencia_v4.csv")
OUT_NPY   = Path("data/embeddings_v4.npy")
OUT_META  = Path("data/embeddings_v4_meta.csv")
MODEL_NAME = "intfloat/multilingual-e5-large"
E5_PREFIX  = "query: "
BATCH_SIZE = 32

def main():
    t0 = datetime.now()
    print("=" * 60)
    print("  OE4 e5_embedder_v2.py")
    print(f"  Inicio: {t0.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\n🎮 Device: {device.upper()}")

    df = pd.read_csv(CORPUS)
    print(f"📂 Corpus: {len(df):,} registros")
    print(f"   Labels: {df['label'].value_counts().to_dict()}")

    print(f"\n🤖 Cargando {MODEL_NAME} (desde caché local)...")
    t1 = datetime.now()
    model = SentenceTransformer(MODEL_NAME, device=device)
    print(f"   Cargado en {(datetime.now()-t1).total_seconds():.1f}s")
    print(f"   Dim: {model.get_sentence_embedding_dimension()}")

    texts = [f"{E5_PREFIX}{t}" for t in df["texto"].tolist()]
    print(f"\n⚡ Generando embeddings ({len(texts):,} textos, batch={BATCH_SIZE})...")
    t2 = datetime.now()
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=True,
        device=device,
        convert_to_numpy=True,
    )
    elapsed = (datetime.now()-t2).total_seconds()
    print(f"\n✅ Shape: {embeddings.shape} | Tiempo: {elapsed:.1f}s")
    print(f"   Norma L2 muestra: {np.linalg.norm(embeddings[0]):.4f} (debe ser ~1.0)")

    # Análisis separabilidad
    print("\n📐 Separabilidad por clase:")
    label_map = {"VIGENTE": 0, "EN_RIESGO": 1, "OBSOLETO": 2}
    centroids = {}
    for lbl, lid in label_map.items():
        mask = df["label"] == lbl
        c = embeddings[mask.values].mean(axis=0)
        c = c / np.linalg.norm(c)
        centroids[lbl] = c
        sims = embeddings[mask.values] @ c
        print(f"   {lbl:12s}: cohesion={sims.mean():.4f}±{sims.std():.4f}  n={mask.sum()}")
    pairs = [("VIGENTE","EN_RIESGO"),("VIGENTE","OBSOLETO"),("EN_RIESGO","OBSOLETO")]
    for a, b in pairs:
        sim = float(centroids[a] @ centroids[b])
        status = "✅" if sim < 0.90 else "⚠️ "
        print(f"   {a} ↔ {b}: {sim:.4f} {status}")

    # Guardar
    np.save(OUT_NPY, embeddings)
    df["vector_idx"] = range(len(df))
    df.to_csv(OUT_META, index=False)
    print(f"\n💾 {OUT_NPY}  ({OUT_NPY.stat().st_size/1e6:.1f} MB)")
    print(f"💾 {OUT_META}")

    total = (datetime.now()-t0).total_seconds()
    print(f"\n✅ Completado en {total:.1f}s")
    print("🔜 Siguiente: python scripts/oe4_classifier_v2.py")

if __name__ == "__main__":
    main()
