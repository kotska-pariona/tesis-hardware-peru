#!/usr/bin/env bash
# =============================================================================
# PE4 — Build Dataset + Train BERT (Opción A: Clasificación desde Títulos)
# Uso: bash pe4_pipeline.sh
# =============================================================================
set -euo pipefail

# ─── Rutas ───────────────────────────────────────────────────────────────────
INPUT="data/raw/MASTER_hardware_peru.csv"
PROCESSED="data/processed"
MODELS="models/pe4_bert_obsolescence"
SCRIPTS="scripts"

mkdir -p "$PROCESSED" "$MODELS" "$SCRIPTS"

echo "============================================================"
echo " PE4 PIPELINE — Obsolescencia de Hardware"
echo "============================================================"

# =============================================================================
# PASO 0 — Instalar dependencias
# =============================================================================
echo ""
echo "[PASO 0] Instalando dependencias..."
pip install -q pandas pyarrow transformers torch scikit-learn tqdm

# =============================================================================
# PASO 1 — Generar pe4_build_dataset.py
# =============================================================================
echo ""
echo "[PASO 1] Generando scripts/pe4_build_dataset.py ..."

cat > "$SCRIPTS/pe4_build_dataset.py" << 'PYEOF'
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
PYEOF

echo "  ✅ pe4_build_dataset.py generado"

# =============================================================================
# PASO 2 — Generar pe4_train_bert.py
# =============================================================================
echo ""
echo "[PASO 2] Generando scripts/pe4_train_bert.py ..."

cat > "$SCRIPTS/pe4_train_bert.py" << 'PYEOF'
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
PYEOF

echo "  ✅ pe4_train_bert.py generado"

# =============================================================================
# PASO 3 — Ejecutar pe4_build_dataset.py
# =============================================================================
echo ""
echo "[PASO 3] Construyendo dataset etiquetado..."
python "$SCRIPTS/pe4_build_dataset.py" \
    --input  "$INPUT" \
    --output "$PROCESSED" \
    --report "$PROCESSED/pe4_label_report.json"

echo ""
echo "============================================================"
echo " ✅ PASO 1 COMPLETADO"
echo " Revisa: $PROCESSED/pe4_labeled_validation_sample.csv"
echo " Luego ejecuta el entrenamiento BERT:"
echo ""
echo "   python scripts/pe4_train_bert.py \\"
echo "       --data   data/processed/pe4_labeled_bert_ready.csv \\"
echo "       --output models/pe4_bert_obsolescence/ \\"
echo "       --epochs 5 --batch 32 --balance_strategy hybrid"
echo "============================================================"
