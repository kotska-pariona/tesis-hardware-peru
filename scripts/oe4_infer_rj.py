"""
OE4 — infer_rj.py
Genera el feature r_j (prob. obsolescencia) para cada SKU del corpus.
r_j = P(OBSOLETO | texto_sku)  ∈ [0.0, 1.0]
INPUT : data/embeddings_v4.npy + data/embeddings_v4_meta.csv
OUTPUT: data/oe4_rj_scores.csv  [sku, r_j, label_pred, label_true, conf]
"""
import torch, torch.nn as nn
import numpy as np
import pandas as pd
from pathlib import Path

EMB_NPY   = Path("data/embeddings_v3.npy")
META_CSV  = Path("data/embeddings_v3_meta.csv")
MODEL_PT  = Path("models/obsolescence_classifier_v2.pt")
OUT_CSV   = Path("data/oe4_rj_scores.csv")

LABEL_NAMES = ["VIGENTE", "EN_RIESGO", "OBSOLETO"]

# ── Misma arquitectura que classifier_v2 ────────────────────────────────
class MLP(nn.Module):
    def __init__(self, in_dim=1024, n_classes=3, dropout=0.3):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 512), nn.BatchNorm1d(512, track_running_stats=False), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(512, 128),    nn.BatchNorm1d(128, track_running_stats=False), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(128, 32),     nn.BatchNorm1d(32,  track_running_stats=False), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(32, n_classes)
        )
    def forward(self, x): return self.net(x)

def main():
    print("=" * 55)
    print("  OE4 infer_rj.py — Generando feature r_j")
    print("=" * 55)

    X    = np.load(EMB_NPY)
    meta = pd.read_csv(META_CSV)
    print(f"  Embeddings: {X.shape}")
    print(f"  Meta rows : {len(meta)}")

    model = MLP()
    ckpt  = torch.load(MODEL_PT, map_location="cpu", weights_only=True)
    # Soportar tanto state_dict directo como dict con clave 'model_state_dict'
    sd = ckpt.get("model_state_dict", ckpt)
    model.load_state_dict(sd, strict=True)
    model.eval()
    print(f"  Modelo cargado: {MODEL_PT}")

    with torch.no_grad():
        logits = model(torch.tensor(X, dtype=torch.float32))
        probs  = torch.softmax(logits, dim=1).numpy()   # (N, 3)

    r_j        = probs[:, 2]          # P(OBSOLETO) — VIGENTE=0, EN_RIESGO=1, OBSOLETO=2
    label_pred = probs.argmax(axis=1)

    df_out = meta[["sku","label","label_id"]].copy()
    df_out["r_j"]        = r_j.round(6)
    df_out["p_vigente"]  = probs[:, 0].round(6)
    df_out["p_en_riesgo"]= probs[:, 1].round(6)
    df_out["p_obsoleto"] = probs[:, 2].round(6)
    df_out["label_pred"] = [LABEL_NAMES[i] for i in label_pred]
    df_out["correct"]    = (df_out["label_pred"] == df_out["label"]).astype(int)

    df_out.to_csv(OUT_CSV, index=False)
    print(f"\n💾 {OUT_CSV}  ({df_out.shape})")

    print("\n📊 Estadísticas r_j por clase:")
    print(df_out.groupby("label")["r_j"].describe().round(4).to_string())

    print("\n📋 Muestra r_j (5 por clase):")
    for lname in LABEL_NAMES:
        sub = df_out[df_out["label"] == lname].head(5)
        print(f"\n  [{lname}]")
        for _, r in sub.iterrows():
            print(f"    sku={str(r['sku'])[:30]}  r_j={r['r_j']:.4f}  pred={r['label_pred']}")

    acc = df_out["correct"].mean()
    print(f"\n✅ Accuracy global: {acc:.4f}")
    print(f"   r_j rango: [{r_j.min():.4f}, {r_j.max():.4f}]")
    print(f"   r_j media OBSOLETO : {df_out[df_out['label']=='OBSOLETO']['r_j'].mean():.4f}")
    print(f"   r_j media EN_RIESGO: {df_out[df_out['label']=='EN_RIESGO']['r_j'].mean():.4f}")
    print(f"   r_j media VIGENTE  : {df_out[df_out['label']=='VIGENTE']['r_j'].mean():.4f}")
    print("\n🔜 Siguiente: integrar r_j en pipeline NSGA-III (OE9)")

if __name__ == "__main__":
    main()
