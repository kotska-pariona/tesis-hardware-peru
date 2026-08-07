"""
scripts/oe4_e5large.py — Path canónico OE4
Clasificación de Obsolescencia Tecnológica con multilingual-E5-large
Generado automáticamente desde: scripts/oe4_classifier_v2.py
HDS-ROI v6.0 — 2026-08-07
"""
import copy
"""
OE4 — classifier_v2.py
MLP sobre embeddings E5-large con CV-5 estratificado.
META: F1-macro >= 0.90
OUTPUT: models/obsolescence_classifier_v2.pt
        data/pe4_e5_ablacion_metrics.json   ← integrado al dashboard
"""
import json, torch, torch.nn as nn
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.metrics import f1_score, classification_report
from sklearn.preprocessing import LabelEncoder
from torch.utils.data import DataLoader, TensorDataset

EMB_NPY    = Path("data/embeddings_v4.npy")
META_CSV   = Path("data/embeddings_v4_meta.csv")
OUT_MODEL  = Path("models/obsolescence_classifier_v2.pt")
OUT_METRICS= Path("data/pe4_e5_ablacion_metrics.json")
SEED       = 42
torch.manual_seed(SEED)
np.random.seed(SEED)

LABEL_NAMES = ["VIGENTE", "EN_RIESGO", "OBSOLETO"]

class MLP(nn.Module):
    def __init__(self, dim=1024, h1=512, h2=128, h3=32, nc=3, d1=0.3, d2=0.2, d3=0.1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, h1), nn.LayerNorm(h1), nn.GELU(), nn.Dropout(d1),
            nn.Linear(h1, h2),  nn.LayerNorm(h2), nn.GELU(), nn.Dropout(d2),
            nn.Linear(h2, h3),  nn.LayerNorm(h3), nn.GELU(), nn.Dropout(d3),
            nn.Linear(h3, nc),
        )
    def forward(self, x): return self.net(x)

def train_fold(X_tr, y_tr, X_val, y_val, device, epochs=150, bs=64, lr=5e-4):
    ds_tr  = TensorDataset(torch.tensor(X_tr, dtype=torch.float32),
                           torch.tensor(y_tr, dtype=torch.long))
    dl_tr  = DataLoader(ds_tr, batch_size=bs, shuffle=True)
    model  = MLP().to(device)
    # Class weights para desbalance residual
    counts = np.bincount(y_tr)
    w      = torch.tensor(1.0/counts * counts.mean(), dtype=torch.float32).to(device)
    crit   = nn.CrossEntropyLoss(weight=w)
    opt    = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched  = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)

    best_f1, best_state, patience, pat_cnt = 0.0, None, 15, 0
    for ep in range(epochs):
        model.train()
        for xb, yb in dl_tr:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        sched.step()
        # Val F1
        model.eval()
        with torch.no_grad():
            preds = model(torch.tensor(X_val, dtype=torch.float32).to(device))
            preds = preds.argmax(dim=1).cpu().numpy()
        f1 = f1_score(y_val, preds, average="macro", zero_division=0)
        if f1 > best_f1:
            best_f1, best_state, pat_cnt = f1, copy.deepcopy(model.state_dict()), 0
        else:
            pat_cnt += 1
            if pat_cnt >= patience: break
    model.load_state_dict(best_state)
    return model, best_f1

def main():
    t0 = datetime.now()
    print("=" * 60)
    print("  OE4 classifier_v2.py — MLP + CV-5")
    print(f"  Inicio: {t0.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n🎮 Device: {device}")

    # Cargar embeddings
    X = np.load(EMB_NPY).astype(np.float32)
    df = pd.read_csv(META_CSV)
    le = LabelEncoder()
    le.classes_ = np.array(LABEL_NAMES)  # VIGENTE=0, EN_RIESGO=1, OBSOLETO=2
    y = le.transform(df["label"].values)
    print(f"📂 X: {X.shape} | y dist: {dict(zip(*np.unique(y, return_counts=True)))}")

    # Split hold-out 15%
    X_dev, X_test, y_dev, y_test = train_test_split(
        X, y, test_size=0.15, stratify=y, random_state=SEED)
    print(f"   Dev: {len(X_dev):,} | Test hold-out: {len(X_test):,}")

    # CV-5 estratificado sobre dev
    print("\n🔄 Cross-Validation 5-fold estratificado...")
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    fold_f1s, best_model_global, best_f1_global = [], None, 0.0

    for fold, (tr_idx, val_idx) in enumerate(skf.split(X_dev, y_dev), 1):
        X_tr, X_val = X_dev[tr_idx], X_dev[val_idx]
        y_tr, y_val = y_dev[tr_idx], y_dev[val_idx]
        model, f1 = train_fold(X_tr, y_tr, X_val, y_val, device)
        fold_f1s.append(f1)
        status = "✅" if f1 >= 0.90 else "⚠️ "
        print(f"   Fold {fold}: F1-macro = {f1:.4f} {status}")
        if f1 > best_f1_global:
            best_f1_global = f1
            best_model_global = copy.deepcopy(model)

    cv_mean = float(np.mean(fold_f1s))
    cv_std  = float(np.std(fold_f1s))
    print(f"\n   CV F1-macro: {cv_mean:.4f} ± {cv_std:.4f}")
    print(f"   {'✅ META ALCANZADA (≥0.90)' if cv_mean >= 0.90 else '⚠️  Por debajo de 0.90'}")

    # Evaluación final en test hold-out
    print("\n📊 Evaluación final en test hold-out...")
    best_model_global.eval()
    with torch.no_grad():
        preds_test = best_model_global(
            torch.tensor(X_test, dtype=torch.float32).to(device)
        ).argmax(dim=1).cpu().numpy()

    test_f1 = f1_score(y_test, preds_test, average="macro", zero_division=0)
    report  = classification_report(
        y_test, preds_test,
        target_names=LABEL_NAMES,
        output_dict=True, zero_division=0
    )
    print(classification_report(y_test, preds_test,
                                 target_names=LABEL_NAMES, zero_division=0))
    print(f"   Test F1-macro: {test_f1:.4f} {'✅' if test_f1 >= 0.90 else '⚠️'}")

    # Guardar modelo
    OUT_MODEL.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model_state_dict": best_model_global.state_dict(),
        "input_dim"       : 1024,
        "n_classes"       : 3,
        "label_names"     : LABEL_NAMES,
        "fold_f1_scores"  : fold_f1s,
        "cv_f1_mean"      : cv_mean,
        "cv_f1_std"       : cv_std,
        "test_f1"         : float(test_f1),
        "hyperparams"     : {"hidden_1":512,"hidden_2":128,"hidden_3":32,
                             "dropout_1":0.3,"dropout_2":0.2,"dropout_3":0.1,
                             "lr":5e-4,"epochs":150,"batch_size":64},
        "corpus_version"  : "v3",
        "corpus_rows"     : len(X),
        "timestamp"       : datetime.now().isoformat(),
    }, OUT_MODEL)
    print(f"\n💾 Modelo: {OUT_MODEL}")

    # pe4_e5_ablacion_metrics.json — para el dashboard
    elapsed = (datetime.now()-t0).total_seconds()
    metrics = {
        "modelo"            : "multilingual-E5-large + MLP-3L",
        "corpus_version"    : "v3",
        "corpus_rows"       : int(len(X)),
        "embedding_dim"     : 1024,
        "cv_folds"          : 5,
        "cv_f1_macro_mean"  : round(cv_mean, 4),
        "cv_f1_macro_std"   : round(cv_std, 4),
        "test_f1_macro"     : round(float(test_f1), 4),
        "meta_alcanzada"    : bool(cv_mean >= 0.90),
        "fold_scores"       : [round(f, 4) for f in fold_f1s],
        "per_class"         : {
            k: {m: round(v,4) for m,v in vals.items()}
            for k,vals in report.items()
            if k in LABEL_NAMES
        },
        "elapsed_sec"       : round(elapsed, 1),
        "timestamp"         : datetime.now().isoformat(),
    }
    with open(OUT_METRICS, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"💾 Métricas: {OUT_METRICS}")

    print("\n" + "=" * 60)
    print(f"✅ Pipeline OE4 completado en {elapsed:.1f}s")
    print(f"   CV  F1-macro : {cv_mean:.4f} ± {cv_std:.4f}")
    print(f"   Test F1-macro: {test_f1:.4f}")
    print("=" * 60)

if __name__ == "__main__":
    main()
