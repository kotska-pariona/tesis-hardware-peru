"""
PE4 — Fine-tuning BERT bilingüe para clasificación de obsolescencia.
Modelo base: dccuchile/bert-base-spanish-wwm-cased
Clases: 0=vigente | 1=transición | 2=obsoleto
"""
import argparse, json, os
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score, classification_report
from sklearn.utils import resample
import torch
from torch.utils.data import Dataset, DataLoader
from transformers import (
    AutoTokenizer, AutoModelForSequenceClassification,
    get_linear_schedule_with_warmup
)
from torch.optim import AdamW
from tqdm import tqdm

MODEL_NAME  = "dccuchile/bert-base-spanish-wwm-cased"
MAX_LEN     = 128
LABEL_NAMES = ["vigente", "transicion", "obsoleto"]

class ObsolescenceDataset(Dataset):
    def __init__(self, texts, labels, tokenizer, max_len):
        self.texts     = texts
        self.labels    = labels
        self.tokenizer = tokenizer
        self.max_len   = max_len

    def __len__(self): return len(self.texts)

    def __getitem__(self, idx):
        enc = self.tokenizer(
            self.texts[idx],
            max_length=self.max_len,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        return {
            "input_ids":      enc["input_ids"].squeeze(),
            "attention_mask": enc["attention_mask"].squeeze(),
            "labels":         torch.tensor(self.labels[idx], dtype=torch.long),
        }

def balance_dataset(df, strategy="hybrid"):
    if strategy == "none": return df
    counts = df["label"].value_counts()
    target = int(counts.median()) if strategy == "hybrid" else counts.max()
    parts  = []
    for lbl in df["label"].unique():
        sub = df[df["label"] == lbl]
        n   = min(target, len(sub)) if strategy == "hybrid" else target
        parts.append(resample(sub, replace=(len(sub) < n), n_samples=n, random_state=42))
    return pd.concat(parts).sample(frac=1, random_state=42)

def evaluate(model, loader, device):
    model.eval()
    preds_all, labels_all = [], []
    with torch.no_grad():
        for batch in loader:
            ids  = batch["input_ids"].to(device)
            mask = batch["attention_mask"].to(device)
            lbls = batch["labels"].to(device)
            out  = model(ids, attention_mask=mask)
            preds = out.logits.argmax(dim=-1)
            preds_all.extend(preds.cpu().numpy())
            labels_all.extend(lbls.cpu().numpy())
    f1 = f1_score(labels_all, preds_all, average="macro", zero_division=0)
    return f1, preds_all, labels_all

def main(args):
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"  Dispositivo: {device}")

    # Cargar datos
    df = pd.read_csv(args.data)
    if args.high_confidence_only:
        df = df[df["confidence"] == "high"].copy()
        print(f"  Alta confianza: {len(df):,} filas")

    df = balance_dataset(df, args.balance_strategy)
    print(f"  Dataset balanceado: {len(df):,} filas")
    print(f"  Distribución: {df['label'].value_counts().to_dict()}")

    # Split 70/15/15
    X, y = df["bert_input"].tolist(), df["label"].tolist()
    X_tr, X_tmp, y_tr, y_tmp = train_test_split(X, y, test_size=0.30, stratify=y, random_state=42)
    X_val, X_te, y_val, y_te = train_test_split(X_tmp, y_tmp, test_size=0.50, stratify=y_tmp, random_state=42)
    print(f"  Train: {len(X_tr):,} | Val: {len(X_val):,} | Test: {len(X_te):,}")

    # Tokenizer + Modelo
    print(f"  Cargando {MODEL_NAME} ...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model     = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=3)
    model.to(device)

    # DataLoaders
    tr_ds  = ObsolescenceDataset(X_tr,  y_tr,  tokenizer, MAX_LEN)
    val_ds = ObsolescenceDataset(X_val, y_val, tokenizer, MAX_LEN)
    te_ds  = ObsolescenceDataset(X_te,  y_te,  tokenizer, MAX_LEN)
    tr_dl  = DataLoader(tr_ds,  batch_size=args.batch, shuffle=True,  num_workers=0)
    val_dl = DataLoader(val_ds, batch_size=args.batch, shuffle=False, num_workers=0)
    te_dl  = DataLoader(te_ds,  batch_size=args.batch, shuffle=False, num_workers=0)

    # Optimizer + Scheduler
    total_steps  = len(tr_dl) * args.epochs
    warmup_steps = int(total_steps * 0.10)
    optimizer    = AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    scheduler    = get_linear_schedule_with_warmup(optimizer, warmup_steps, total_steps)

    # Entrenamiento
    best_f1, patience_cnt = 0.0, 0
    best_model_path = output_dir / "best_model"

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0
        for batch in tqdm(tr_dl, desc=f"  Epoch {epoch}/{args.epochs}"):
            ids   = batch["input_ids"].to(device)
            mask  = batch["attention_mask"].to(device)
            lbls  = batch["labels"].to(device)
            optimizer.zero_grad()
            out   = model(ids, attention_mask=mask, labels=lbls)
            loss  = out.loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            total_loss += loss.item()

        avg_loss = total_loss / len(tr_dl)
        val_f1, _, _ = evaluate(model, val_dl, device)
        print(f"  Epoch {epoch} | Loss: {avg_loss:.4f} | Val F1-macro: {val_f1:.4f}")

        if val_f1 > best_f1:
            best_f1 = val_f1
            patience_cnt = 0
            model.save_pretrained(best_model_path)
            tokenizer.save_pretrained(best_model_path)
            print(f"  ✅ Nuevo mejor modelo guardado (F1={best_f1:.4f})")
        else:
            patience_cnt += 1
            if patience_cnt >= args.patience:
                print(f"  ⏹ Early stopping en epoch {epoch}")
                break

    # Evaluación final en test
    print("\n  Cargando mejor modelo para evaluación final ...")
    model = AutoModelForSequenceClassification.from_pretrained(best_model_path)
    model.to(device)
    test_f1, preds, labels = evaluate(model, te_dl, device)
    report = classification_report(labels, preds, target_names=LABEL_NAMES, output_dict=True)

    print(f"\n  ── RESULTADOS FINALES ────────────────────────")
    print(f"  F1-macro (test): {test_f1:.4f}  {'✅ META ALCANZADA' if test_f1 >= 0.90 else '⚠️ Por debajo de 0.90'}")
    print(classification_report(labels, preds, target_names=LABEL_NAMES))

    metrics = {
        "f1_macro_test": round(test_f1, 4),
        "meta_alcanzada": test_f1 >= 0.90,
        "best_val_f1":    round(best_f1, 4),
        "classification_report": report,
    }
    metrics_path = output_dir / "pe4_bert_metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"  Guardado: {metrics_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data",                 default="data/processed/pe4_labeled_bert_ready.csv")
    parser.add_argument("--output",               default="models/pe4_bert_obsolescence")
    parser.add_argument("--epochs",    type=int,  default=5)
    parser.add_argument("--batch",     type=int,  default=32)
    parser.add_argument("--lr",        type=float,default=2e-5)
    parser.add_argument("--patience",  type=int,  default=2)
    parser.add_argument("--balance_strategy",     default="hybrid", choices=["none","oversample","hybrid"])
    parser.add_argument("--high_confidence_only", action="store_true")
    args = parser.parse_args()
    main(args)
