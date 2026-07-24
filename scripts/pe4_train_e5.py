# -*- coding: utf-8 -*-
"""
PE4 — Ablación Config A
Modelo : intfloat/multilingual-e5-large
Tarea  : Clasificación de obsolescencia (3 clases)
Dataset: pe4_labeled_bert_clean.csv (29,141 registros)
"""

import argparse
import json
import os
import random

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import (classification_report, f1_score,
                              accuracy_score)
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_class_weight
from torch.utils.data import Dataset, DataLoader
from transformers import (AutoTokenizer, AutoModelForSequenceClassification,
                           get_linear_schedule_with_warmup)
from torch.optim import AdamW

# ── Reproducibilidad ──────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(SEED)

# ─────────────────────────────────────────────────────────────────
# ARGUMENTOS
# ─────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="PE4 Ablación — E5-large")
    p.add_argument("--data",    required=True,  help="Ruta al CSV limpio")
    p.add_argument("--output",  required=True,  help="Carpeta de salida")
    p.add_argument("--epochs",  type=int, default=5)
    p.add_argument("--batch",   type=int, default=16)
    p.add_argument("--lr",      type=float, default=2e-5)
    p.add_argument("--max_len", type=int, default=128)
    p.add_argument("--balance_strategy", default="hybrid",
                   choices=["none", "oversample", "class_weight", "hybrid"])
    return p.parse_args()

# ─────────────────────────────────────────────────────────────────
# DATASET
# ─────────────────────────────────────────────────────────────────
class ObsolescenceDataset(Dataset):
    def __init__(self, texts, labels, tokenizer, max_len):
        self.texts     = texts
        self.labels    = labels
        self.tokenizer = tokenizer
        self.max_len   = max_len

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, idx):
        # E5 requiere prefijo "query: " para clasificación
        text = f"query: {self.texts[idx]}"
        enc  = self.tokenizer(
            text,
            max_length=self.max_len,
            padding="max_length",
            truncation=True,
            return_tensors="pt"
        )
        return {
            "input_ids":      enc["input_ids"].squeeze(),
            "attention_mask": enc["attention_mask"].squeeze(),
            "label":          torch.tensor(self.labels[idx], dtype=torch.long)
        }

# ─────────────────────────────────────────────────────────────────
# OVERSAMPLE de la clase minoritaria
# ─────────────────────────────────────────────────────────────────
def oversample_minority(df, label_col="label", seed=42):
    counts  = df[label_col].value_counts()
    max_cnt = counts.max()
    parts   = [df]
    for cls, cnt in counts.items():
        if cnt < max_cnt:
            deficit = max_cnt - cnt
            sample  = df[df[label_col] == cls].sample(
                deficit, replace=True, random_state=seed)
            parts.append(sample)
    return pd.concat(parts).sample(frac=1, random_state=seed).reset_index(drop=True)

# ─────────────────────────────────────────────────────────────────
# ENTRENAMIENTO
# ─────────────────────────────────────────────────────────────────
def train_epoch(model, loader, optimizer, scheduler, device, class_weights=None):
    model.train()
    total_loss = 0.0
    criterion  = (torch.nn.CrossEntropyLoss(weight=class_weights.to(device))
                  if class_weights is not None
                  else torch.nn.CrossEntropyLoss())
    for batch in loader:
        optimizer.zero_grad()
        input_ids = batch["input_ids"].to(device)
        attn_mask = batch["attention_mask"].to(device)
        labels    = batch["label"].to(device)

        outputs = model(input_ids=input_ids, attention_mask=attn_mask)
        loss    = criterion(outputs.logits, labels)
        loss.backward()

        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        scheduler.step()
        total_loss += loss.item()

    return total_loss / len(loader)

def eval_epoch(model, loader, device):
    model.eval()
    all_preds, all_labels = [], []
    with torch.no_grad():
        for batch in loader:
            input_ids = batch["input_ids"].to(device)
            attn_mask = batch["attention_mask"].to(device)
            labels    = batch["label"].to(device)
            outputs   = model(input_ids=input_ids, attention_mask=attn_mask)
            preds     = outputs.logits.argmax(dim=-1)
            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())

    f1  = f1_score(all_labels, all_preds, average="macro", zero_division=0)
    acc = accuracy_score(all_labels, all_preds)
    return f1, acc, all_preds, all_labels

# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────
def main():
    args   = parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    os.makedirs(args.output, exist_ok=True)

    print("=" * 60)
    print("  PE4 ABLACIÓN — multilingual-E5-large")
    print("=" * 60)
    print(f"  Device  : {device}")
    print(f"  Epochs  : {args.epochs}")
    print(f"  Batch   : {args.batch}")
    print(f"  LR      : {args.lr}")
    print(f"  Max len : {args.max_len}")
    print(f"  Balance : {args.balance_strategy}")
    print("=" * 60)

    # ── Cargar datos ───────────────────────────────────────────
    df = pd.read_csv(args.data)
    print(f"\n📥 Dataset: {len(df):,} registros")
    print(f"   Columnas: {list(df.columns)}")

    # Detectar columna de texto
    text_col = None
    for col in ["bert_input", "text", "titulo", "nombre", "descripcion"]:
        if col in df.columns:
            text_col = col
            break
    if text_col is None:
        text_col = df.select_dtypes(include="object").columns[0]
    print(f"   Columna texto: '{text_col}'")

    # ── Split estratificado 65/15/20 ───────────────────────────
    idx    = np.arange(len(df))
    labels = df["label"].values

    idx_train, idx_temp = train_test_split(
        idx, test_size=0.35, random_state=SEED, stratify=labels)
    idx_val, idx_test = train_test_split(
        idx_temp, test_size=0.20/0.35, random_state=SEED,
        stratify=labels[idx_temp])

    df_train = df.iloc[idx_train].reset_index(drop=True)
    df_val   = df.iloc[idx_val].reset_index(drop=True)
    df_test  = df.iloc[idx_test].reset_index(drop=True)

    print(f"\n📐 Split:")
    print(f"   Train : {len(df_train):,}")
    print(f"   Val   : {len(df_val):,}")
    print(f"   Test  : {len(df_test):,}")

    # ── Balanceo ───────────────────────────────────────────────
    class_weights = None
    if args.balance_strategy in ("oversample", "hybrid"):
        df_train = oversample_minority(df_train, seed=SEED)
        print(f"   Train (oversampled): {len(df_train):,}")

    if args.balance_strategy in ("class_weight", "hybrid"):
        cw = compute_class_weight(
            "balanced",
            classes=np.unique(labels),
            y=df_train["label"].values
        )
        class_weights = torch.tensor(cw, dtype=torch.float)
        print(f"   Class weights: {cw.round(3)}")

    # ── Tokenizer y Modelo ─────────────────────────────────────
    MODEL_NAME = "intfloat/multilingual-e5-large"
    print(f"\n🤗 Cargando {MODEL_NAME}...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model     = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME, num_labels=3, ignore_mismatched_sizes=True)
    model.to(device)

    # ── DataLoaders ────────────────────────────────────────────
    train_ds = ObsolescenceDataset(
        df_train[text_col].tolist(), df_train["label"].tolist(),
        tokenizer, args.max_len)
    val_ds   = ObsolescenceDataset(
        df_val[text_col].tolist(), df_val["label"].tolist(),
        tokenizer, args.max_len)
    test_ds  = ObsolescenceDataset(
        df_test[text_col].tolist(), df_test["label"].tolist(),
        tokenizer, args.max_len)

    train_loader = DataLoader(train_ds, batch_size=args.batch, shuffle=True,  num_workers=2)
    val_loader   = DataLoader(val_ds,   batch_size=args.batch, shuffle=False, num_workers=2)
    test_loader  = DataLoader(test_ds,  batch_size=args.batch, shuffle=False, num_workers=2)

    # ── Optimizer y Scheduler ──────────────────────────────────
    optimizer = AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    total_steps = len(train_loader) * args.epochs
    scheduler   = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(0.1 * total_steps),
        num_training_steps=total_steps
    )

    # ── Entrenamiento ──────────────────────────────────────────
    best_f1       = 0.0
    best_model_path = os.path.join(args.output, "best_model")
    history       = []

    print(f"\n🚀 Iniciando entrenamiento ({args.epochs} épocas)...")
    print("=" * 60)

    for epoch in range(1, args.epochs + 1):
        train_loss        = train_epoch(model, train_loader, optimizer,
                                        scheduler, device, class_weights)
        val_f1, val_acc, _, _ = eval_epoch(model, val_loader, device)

        history.append({
            "epoch": epoch, "loss": round(train_loss, 4),
            "val_f1_macro": round(val_f1, 4), "val_acc": round(val_acc, 4)
        })

        print(f"  Época {epoch}/{args.epochs} | "
              f"Loss: {train_loss:.4f} | "
              f"Val F1-macro: {val_f1:.4f} | "
              f"Val Acc: {val_acc:.4f}")

        if val_f1 > best_f1:
            best_f1 = val_f1
            model.save_pretrained(best_model_path)
            tokenizer.save_pretrained(best_model_path)
            print(f"    💾 Mejor modelo guardado (F1={best_f1:.4f})")

    # ── Evaluación final en Test ───────────────────────────────
    print("\n" + "=" * 60)
    print("  📊 EVALUACIÓN FINAL — Test Set")
    print("=" * 60)

    best_model = AutoModelForSequenceClassification.from_pretrained(
        best_model_path, num_labels=3, ignore_mismatched_sizes=True)
    best_model.to(device)

    test_f1, test_acc, preds, true_labels = eval_epoch(
        best_model, test_loader, device)

    nombres = {0: "Vigente", 1: "Transicion", 2: "Obsoleto"}
    report  = classification_report(
        true_labels, preds,
        target_names=[nombres[i] for i in range(3)],
        output_dict=True, zero_division=0
    )

    print(classification_report(
        true_labels, preds,
        target_names=[nombres[i] for i in range(3)],
        zero_division=0
    ))

    # ── Guardar métricas ───────────────────────────────────────
    metrics = {
        "model":          MODEL_NAME,
        "dataset":        args.data,
        "n_train":        len(df_train),
        "n_val":          len(df_val),
        "n_test":         len(df_test),
        "epochs":         args.epochs,
        "batch_size":     args.batch,
        "balance":        args.balance_strategy,
        "f1_macro":       round(test_f1, 4),
        "accuracy":       round(test_acc, 4),
        "f1_vigente":     round(report["Vigente"]["f1-score"], 4),
        "f1_transicion":  round(report["Transicion"]["f1-score"], 4),
        "f1_obsoleto":    round(report["Obsoleto"]["f1-score"], 4),
        "history":        history,
        "best_val_f1":    round(best_f1, 4),
        # Comparativa directa con Config B'
        "vs_bert_base": {
            "bert_f1_macro":  0.9921,
            "e5_f1_macro":    round(test_f1, 4),
            "delta":          round(test_f1 - 0.9921, 4)
        }
    }

    metrics_path = os.path.join(args.output, "pe4_e5_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Métricas guardadas: {metrics_path}")
    print("=" * 60)
    print(f"  🎯 F1-macro (Test)  : {test_f1:.4f}")
    print(f"  📊 Accuracy         : {test_acc:.4f}")
    print(f"  🆚 vs BERT-base     : {test_f1 - 0.9921:+.4f}")
    print("=" * 60)

    if test_f1 >= 0.90:
        print(f"  🏆 META ALCANZADA ✅")
    else:
        print(f"  ⚠️  F1 < 0.90 — revisar hiperparámetros")

if __name__ == "__main__":
    main()