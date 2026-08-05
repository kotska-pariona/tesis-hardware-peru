# =============================================================================
# classifier.py — OE4: Clasificador MLP sobre Embeddings E5-large
# Proyecto: HDS-ROI v4.0 | Universidad Nacional de Ingeniería
# Autor: Kotska Rony Pariona Martinez
# Fecha: 2026-07-30
#
# INPUT : data/embeddings_obsolescencia.npy  → (82, 1024)
#         data/embeddings_meta.csv           → texto + label + label_id
#
# OUTPUT: models/obsolescence_classifier.pt  → modelo entrenado
#         results/obsolescencia_scores.csv   → r_j por SKU
#         results/classification_report.txt  → métricas F1
#         results/confusion_matrix.png       → visualización
#
# Fix v2: BatchNorm1d → LayerNorm + drop_last=True en DataLoader
# =============================================================================

import os
import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use("Agg")

from pathlib import Path
from datetime import datetime

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import (classification_report, confusion_matrix,
                              f1_score, accuracy_score)
from sklearn.utils.class_weight import compute_class_weight

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# 0. CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

DATA_DIR    = Path("data")
MODEL_DIR   = Path("models")
RESULTS_DIR = Path("results")
LOG_FILE    = DATA_DIR / "classifier_log.txt"

INPUT_NPY   = DATA_DIR    / "embeddings_obsolescencia.npy"
INPUT_META  = DATA_DIR    / "embeddings_meta.csv"
MODEL_PATH  = MODEL_DIR   / "obsolescence_classifier.pt"
SCORES_CSV  = RESULTS_DIR / "obsolescencia_scores.csv"
REPORT_TXT  = RESULTS_DIR / "classification_report.txt"
CM_PNG      = RESULTS_DIR / "confusion_matrix.png"

# Hiperparámetros
HIDDEN_1    = 256
HIDDEN_2    = 64
DROPOUT_1   = 0.3
DROPOUT_2   = 0.2
LR          = 1e-3
EPOCHS      = 200
PATIENCE    = 20
BATCH_SIZE  = 16
K_FOLDS     = 5
SEED        = 42
N_CLASSES   = 3

LABEL_NAMES = ["VIGENTE", "EN_RIESGO", "OBSOLETO"]

torch.manual_seed(SEED)
np.random.seed(SEED)

# ─────────────────────────────────────────────────────────────────────────────
# 1. UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def ensure_dirs():
    for d in [MODEL_DIR, RESULTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# 2. ARQUITECTURA MLP — Fix: LayerNorm en lugar de BatchNorm1d
# ─────────────────────────────────────────────────────────────────────────────

class ObsolescenceMLP(nn.Module):
    """
    MLP 3 capas para clasificación de obsolescencia.
    Usa LayerNorm (funciona con batch_size=1, sin restricciones).
    Input : embeddings E5-large (1024-dim, L2-normalizados)
    Output: logits (3 clases)
    """
    def __init__(self, input_dim: int = 1024):
        super().__init__()
        self.net = nn.Sequential(
            # Capa 1
            nn.Linear(input_dim, HIDDEN_1),
            nn.LayerNorm(HIDDEN_1),       # ← Fix: LayerNorm (no BatchNorm)
            nn.ReLU(),
            nn.Dropout(DROPOUT_1),
            # Capa 2
            nn.Linear(HIDDEN_1, HIDDEN_2),
            nn.LayerNorm(HIDDEN_2),       # ← Fix: LayerNorm
            nn.ReLU(),
            nn.Dropout(DROPOUT_2),
            # Capa 3 — salida
            nn.Linear(HIDDEN_2, N_CLASSES),
        )

    def forward(self, x):
        return self.net(x)

    def predict_proba(self, x):
        with torch.no_grad():
            logits = self.forward(x)
            return torch.softmax(logits, dim=-1)

# ─────────────────────────────────────────────────────────────────────────────
# 3. CARGA DE DATOS
# ─────────────────────────────────────────────────────────────────────────────

def load_data():
    if not INPUT_NPY.exists():
        raise FileNotFoundError(
            f"No se encontró {INPUT_NPY}\nEjecuta primero: python e5_embedder.py"
        )
    if not INPUT_META.exists():
        raise FileNotFoundError(f"No se encontró {INPUT_META}")

    X  = np.load(INPUT_NPY).astype(np.float32)
    df = pd.read_csv(INPUT_META, encoding="utf-8")
    y  = df["label_id"].values.astype(np.int64)

    log(f"📂 Datos cargados: X={X.shape}, y={y.shape}")
    log(f"   Distribución de clases:")
    for i, name in enumerate(LABEL_NAMES):
        n = (y == i).sum()
        log(f"   {name:12s}: {n:>3} ({n/len(y)*100:.1f}%)")

    return X, y, df

# ─────────────────────────────────────────────────────────────────────────────
# 4. ENTRENAMIENTO CON STRATIFIED K-FOLD
# ─────────────────────────────────────────────────────────────────────────────

def train_fold(X_train, y_train, X_val, y_val,
               class_weights_tensor, device, fold_idx):
    """Entrena un fold y retorna el mejor modelo + F1."""

    model     = ObsolescenceMLP(input_dim=X_train.shape[1]).to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights_tensor)
    optimizer = optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)

    X_tr = torch.tensor(X_train).to(device)
    y_tr = torch.tensor(y_train).to(device)
    X_vl = torch.tensor(X_val).to(device)
    y_vl = torch.tensor(y_val).to(device)

    dataset = TensorDataset(X_tr, y_tr)
    # drop_last=True evita batch de tamaño 1 (seguro con ≥65 muestras/fold)
    loader  = DataLoader(dataset, batch_size=BATCH_SIZE,
                         shuffle=True, drop_last=True)

    best_f1          = 0.0
    best_state       = None
    patience_counter = 0

    for epoch in range(EPOCHS):
        # ── Train
        model.train()
        for xb, yb in loader:
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()
        scheduler.step()

        # ── Validate
        model.eval()
        with torch.no_grad():
            preds_val = model(X_vl).argmax(dim=1).cpu().numpy()

        f1 = f1_score(y_val, preds_val, average="macro", zero_division=0)

        if f1 > best_f1:
            best_f1          = f1
            best_state       = {k: v.clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= PATIENCE:
                log(f"   Fold {fold_idx} | Early stop epoch {epoch+1:>3} "
                    f"| best F1={best_f1:.4f}")
                break

    model.load_state_dict(best_state)
    return model, best_f1

# ─────────────────────────────────────────────────────────────────────────────
# 5. EVALUACIÓN FINAL
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_model(model, X, y, device):
    model.eval()
    X_t = torch.tensor(X).to(device)
    with torch.no_grad():
        proba = model.predict_proba(X_t).cpu().numpy()
    preds = proba.argmax(axis=1)
    return preds, proba

# ─────────────────────────────────────────────────────────────────────────────
# 6. VISUALIZACIÓN — CONFUSION MATRIX
# ─────────────────────────────────────────────────────────────────────────────

def plot_confusion_matrix(y_true, y_pred, fold_f1_scores):
    cm      = confusion_matrix(y_true, y_pred)
    cm_norm = cm.astype(float) / cm.sum(axis=1, keepdims=True)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle(
        f"OE4 — Clasificador Obsolescencia | E5-large + MLP\n"
        f"F1-macro CV: {np.mean(fold_f1_scores):.4f} "
        f"± {np.std(fold_f1_scores):.4f}",
        fontsize=13, fontweight="bold"
    )

    # Matriz absoluta
    im0 = axes[0].imshow(cm, cmap="Blues")
    axes[0].set_title("Matriz de Confusión (conteos)", fontsize=11)
    axes[0].set_xticks(range(N_CLASSES))
    axes[0].set_xticklabels(LABEL_NAMES, rotation=20)
    axes[0].set_yticks(range(N_CLASSES))
    axes[0].set_yticklabels(LABEL_NAMES)
    axes[0].set_xlabel("Predicho"); axes[0].set_ylabel("Real")
    for i in range(N_CLASSES):
        for j in range(N_CLASSES):
            axes[0].text(j, i, str(cm[i, j]),
                         ha="center", va="center",
                         color="white" if cm[i,j] > cm.max()/2 else "black",
                         fontsize=14, fontweight="bold")
    plt.colorbar(im0, ax=axes[0])

    # Matriz normalizada
    im1 = axes[1].imshow(cm_norm, cmap="RdYlGn", vmin=0, vmax=1)
    axes[1].set_title("Matriz Normalizada (recall por clase)", fontsize=11)
    axes[1].set_xticks(range(N_CLASSES))
    axes[1].set_xticklabels(LABEL_NAMES, rotation=20)
    axes[1].set_yticks(range(N_CLASSES))
    axes[1].set_yticklabels(LABEL_NAMES)
    axes[1].set_xlabel("Predicho"); axes[1].set_ylabel("Real")
    for i in range(N_CLASSES):
        for j in range(N_CLASSES):
            axes[1].text(j, i, f"{cm_norm[i,j]:.2f}",
                         ha="center", va="center",
                         color="white" if cm_norm[i,j] < 0.3 or cm_norm[i,j] > 0.7 else "black",
                         fontsize=13, fontweight="bold")
    plt.colorbar(im1, ax=axes[1])

    # Mini-gráfico F1 por fold
    ax_inset = fig.add_axes([0.42, 0.12, 0.12, 0.25])
    ax_inset.bar(range(1, K_FOLDS+1), fold_f1_scores,
                 color="#4C72B0", alpha=0.8)
    ax_inset.axhline(np.mean(fold_f1_scores),
                     color="red", linestyle="--", linewidth=1)
    ax_inset.set_title("F1 / Fold", fontsize=8)
    ax_inset.set_ylim(0, 1)
    ax_inset.set_xticks(range(1, K_FOLDS+1))
    ax_inset.tick_params(labelsize=7)

    plt.tight_layout()
    plt.savefig(CM_PNG, dpi=150, bbox_inches="tight")
    plt.close()
    log(f"📊 Confusion matrix guardada: {CM_PNG}")

# ─────────────────────────────────────────────────────────────────────────────
# 7. CALCULAR SCORE r_j ∈ [0, 1]
# ─────────────────────────────────────────────────────────────────────────────

def compute_rj(proba: np.ndarray) -> np.ndarray:
    """
    r_j ∈ [0, 1] — Score de riesgo de obsolescencia.

    Fórmula:
      r_j = 0.5 * P(EN_RIESGO) + 1.0 * P(OBSOLETO)

    Interpretación:
      r_j → 0.0 : VIGENTE   (sin riesgo)
      r_j → 0.5 : EN_RIESGO (riesgo moderado)
      r_j → 1.0 : OBSOLETO  (riesgo máximo)
    """
    r_j = 0.5 * proba[:, 1] + 1.0 * proba[:, 2]
    return np.clip(r_j, 0.0, 1.0)

# ─────────────────────────────────────────────────────────────────────────────
# 8. GUARDAR RESULTADOS
# ─────────────────────────────────────────────────────────────────────────────

def save_results(df, y_true, y_pred, proba, fold_f1_scores):
    # 8.1 Classification report
    report   = classification_report(
        y_true, y_pred,
        target_names=LABEL_NAMES,
        digits=4, zero_division=0
    )
    acc      = accuracy_score(y_true, y_pred)
    f1_macro = f1_score(y_true, y_pred, average="macro", zero_division=0)

    report_full = (
        f"OE4 — Clasificador Obsolescencia | E5-large + MLP\n"
        f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{'='*55}\n\n"
        f"Stratified K-Fold (k={K_FOLDS}) F1-macro por fold:\n"
        + "".join([f"  Fold {i+1}: {s:.4f}\n" for i, s in enumerate(fold_f1_scores)])
        + f"  Media : {np.mean(fold_f1_scores):.4f} ± {np.std(fold_f1_scores):.4f}\n\n"
        f"{'='*55}\n"
        f"Evaluación sobre corpus completo:\n\n"
        + report
        + f"\nAccuracy : {acc:.4f}"
        f"\nF1-macro : {f1_macro:.4f}"
    )

    with open(REPORT_TXT, "w", encoding="utf-8") as f:
        f.write(report_full)
    log(f"📄 Classification report: {REPORT_TXT}")
    print("\n" + report_full)

    # 8.2 Scores CSV con r_j
    r_j = compute_rj(proba)

    out_cols       = ["sku", "producto", "marca", "categoria",
                      "label", "precio_usd", "fuente"]
    out_cols_exist = [c for c in out_cols if c in df.columns]

    scores_df = df[out_cols_exist].copy()
    scores_df["label_true"]  = [LABEL_NAMES[i] for i in y_true]
    scores_df["label_pred"]  = [LABEL_NAMES[i] for i in y_pred]
    scores_df["p_vigente"]   = proba[:, 0].round(4)
    scores_df["p_en_riesgo"] = proba[:, 1].round(4)
    scores_df["p_obsoleto"]  = proba[:, 2].round(4)
    scores_df["r_j"]         = r_j.round(4)
    scores_df["correcto"]    = (y_true == y_pred)

    scores_df = scores_df.sort_values("r_j", ascending=False).reset_index(drop=True)
    scores_df.to_csv(SCORES_CSV, index=False, encoding="utf-8")
    log(f"💾 Scores r_j guardados: {SCORES_CSV}  ({len(scores_df):,} registros)")

    # Preview top 10
    log("\n📋 Top 10 SKUs por riesgo de obsolescencia (r_j):")
    log(f"   {'Producto':<45} {'Label':>10} {'r_j':>6}")
    log(f"   {'-'*65}")
    for _, row in scores_df.head(10).iterrows():
        prod  = str(row.get("producto", row.get("sku", "N/A")))[:44]
        label = row["label_pred"]
        rj    = row["r_j"]
        log(f"   {prod:<45} {label:>10} {rj:>6.4f}")

    return scores_df

# ─────────────────────────────────────────────────────────────────────────────
# 9. MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ensure_dirs()
    log("=" * 60)
    log("  classifier.py — OE4 MLP Classifier  [v2 — LayerNorm fix]")
    log(f"  Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"🎮 Device: {device.upper()}")

    # ── Cargar datos
    X, y, df = load_data()

    # ── Class weights
    cw        = compute_class_weight("balanced", classes=np.unique(y), y=y)
    cw_tensor = torch.tensor(cw, dtype=torch.float32).to(device)
    log(f"\n⚖️  Class weights: " +
        " | ".join([f"{LABEL_NAMES[i]}={cw[i]:.3f}" for i in range(N_CLASSES)]))

    # ── Stratified K-Fold
    log(f"\n🔁 Stratified K-Fold (k={K_FOLDS}):")
    skf             = StratifiedKFold(n_splits=K_FOLDS, shuffle=True, random_state=SEED)
    fold_f1_scores  = []
    best_overall_f1 = 0.0
    best_model      = None

    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
        X_tr, X_vl = X[train_idx], X[val_idx]
        y_tr, y_vl = y[train_idx], y[val_idx]

        model, f1 = train_fold(X_tr, y_tr, X_vl, y_vl,
                                cw_tensor, device, fold+1)
        fold_f1_scores.append(f1)
        log(f"   Fold {fold+1}/{K_FOLDS} | val F1-macro = {f1:.4f} | "
            f"train={len(y_tr)} val={len(y_vl)}")

        if f1 > best_overall_f1:
            best_overall_f1 = f1
            best_model      = model

    log(f"\n✅ CV completado:")
    log(f"   F1-macro media : {np.mean(fold_f1_scores):.4f}")
    log(f"   F1-macro std   : {np.std(fold_f1_scores):.4f}")
    log(f"   Mejor fold F1  : {best_overall_f1:.4f}")

    # ── Reentrenar modelo final con corpus completo
    log("\n🔄 Reentrenando modelo final con corpus completo...")
    final_model = ObsolescenceMLP(input_dim=X.shape[1]).to(device)
    criterion   = nn.CrossEntropyLoss(weight=cw_tensor)
    optimizer   = optim.AdamW(final_model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler   = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)

    X_t = torch.tensor(X).to(device)
    y_t = torch.tensor(y).to(device)
    ds  = TensorDataset(X_t, y_t)
    dl  = DataLoader(ds, batch_size=BATCH_SIZE, shuffle=True, drop_last=True)

    best_loss        = float("inf")
    patience_counter = 0
    best_final_state = None

    for epoch in range(EPOCHS):
        final_model.train()
        epoch_loss = 0.0
        for xb, yb in dl:
            optimizer.zero_grad()
            loss = criterion(final_model(xb), yb)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
        scheduler.step()
        avg_loss = epoch_loss / len(dl)

        if avg_loss < best_loss:
            best_loss        = avg_loss
            best_final_state = {k: v.clone() for k, v in final_model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= PATIENCE:
                log(f"   Early stop en epoch {epoch+1} | best loss={best_loss:.4f}")
                break

    final_model.load_state_dict(best_final_state)

    # ── Guardar modelo
    torch.save({
        "model_state_dict" : final_model.state_dict(),
        "input_dim"        : X.shape[1],
        "n_classes"        : N_CLASSES,
        "label_names"      : LABEL_NAMES,
        "fold_f1_scores"   : fold_f1_scores,
        "cv_f1_mean"       : float(np.mean(fold_f1_scores)),
        "cv_f1_std"        : float(np.std(fold_f1_scores)),
        "hyperparams"      : {
            "hidden_1": HIDDEN_1, "hidden_2": HIDDEN_2,
            "dropout_1": DROPOUT_1, "dropout_2": DROPOUT_2,
            "lr": LR, "epochs": EPOCHS, "batch_size": BATCH_SIZE,
        },
        "timestamp"        : datetime.now().isoformat(),
    }, MODEL_PATH)
    log(f"\n💾 Modelo guardado: {MODEL_PATH}")

    # ── Evaluación final
    y_pred, proba = evaluate_model(final_model, X, y, device)

    # ── Visualización
    plot_confusion_matrix(y, y_pred, fold_f1_scores)

    # ── Guardar resultados
    save_results(df, y, y_pred, proba, fold_f1_scores)

    log("\n" + "=" * 60)
    log("✅ classifier.py completado  [v2]")
    log(f"   Modelo   : {MODEL_PATH}")
    log(f"   Scores   : {SCORES_CSV}")
    log(f"   Reporte  : {REPORT_TXT}")
    log(f"   CM plot  : {CM_PNG}")
    log(f"\n   F1-macro CV : {np.mean(fold_f1_scores):.4f} ± {np.std(fold_f1_scores):.4f}")
    log("\n🔜 Siguiente paso: integrar r_j en dashboard.py (OE9)")
    log("=" * 60)


if __name__ == "__main__":
    main()