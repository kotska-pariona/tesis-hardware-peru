"""
evaluate_models.py
==================
Evaluación completa de OE3 (LightGBM + Mondrian) y OE4 (BERT/E5 Obsolescencia)
Tesis: Sistema Híbrido DL + Computación Evolutiva — Kotska Pariona (UNI-FIIS)

Uso:
    python scripts/evaluate_models.py
    python scripts/evaluate_models.py --only oe3
    python scripts/evaluate_models.py --only oe4
"""

import os
import sys
import json
import pickle
import argparse
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from pathlib import Path

# ── Rutas base ────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
DATA_DIR   = ROOT / "data" / "processed"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

SEED = 42
np.random.seed(SEED)

# ══════════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ══════════════════════════════════════════════════════════════════════════════

def mape(y_true, y_pred):
    """Mean Absolute Percentage Error — evita división por cero."""
    y_true, y_pred = np.array(y_true), np.array(y_pred)
    mask = y_true != 0
    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100

def smape(y_true, y_pred):
    """Symmetric MAPE."""
    y_true, y_pred = np.array(y_true), np.array(y_pred)
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2
    mask = denom != 0
    return np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom[mask]) * 100

def rmse(y_true, y_pred):
    return np.sqrt(np.mean((np.array(y_true) - np.array(y_pred))**2))

def r2(y_true, y_pred):
    y_true = np.array(y_true)
    ss_res = np.sum((y_true - np.array(y_pred))**2)
    ss_tot = np.sum((y_true - np.mean(y_true))**2)
    return 1 - ss_res / ss_tot if ss_tot != 0 else 0.0

def coverage(y_true, lower, upper):
    """Cobertura empírica del intervalo de predicción."""
    y_true = np.array(y_true)
    return np.mean((y_true >= lower) & (y_true <= upper)) * 100

def interval_width(lower, upper):
    return np.mean(np.array(upper) - np.array(lower))

def print_section(title):
    print("\n" + "═"*60)
    print(f"  {title}")
    print("═"*60)

def status(ok, meta_label=""):
    icon = "✅" if ok else "❌"
    return f"{icon} {meta_label}"

# ══════════════════════════════════════════════════════════════════════════════
# OE3 — LightGBM + Mondrian Conformal Prediction
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_oe3():
    print_section("OE3 — LightGBM + Mondrian Conformal Prediction")
    print("  Meta: MAPE < 1% | Cobertura Mondrian 93–97%\n")

    # ── 1. Cargar modelos ──────────────────────────────────────────────────
    print("📦 Cargando modelos...")

    try:
        with open(MODELS_DIR / "lgbm_e1b_tuned.pkl", "rb") as f:
            lgbm_model = pickle.load(f)
        print("  ✓ lgbm_e1b_tuned.pkl")
    except Exception as e:
        print(f"  ✗ lgbm_e1b_tuned.pkl — {e}")
        return None

    # Cargar normalizador
    try:
        with open(MODELS_DIR / "zscore_normalizer.pkl", "rb") as f:
            normalizer = pickle.load(f)
        print("  ✓ zscore_normalizer.pkl")
    except Exception as e:
        print(f"  ⚠ zscore_normalizer.pkl — {e} (continuando sin normalizar)")
        normalizer = None

    # Cargar Mondrian (preferir v4 como versión final)
    mondrian_model = None
    for fname in ["lgbm_e2c_mondrian_cal.pkl", "mondrian_q_final_v4.pkl", "mondrian_q_final.pkl"]:
        try:
            with open(MODELS_DIR / fname, "rb") as f:
                mondrian_model = pickle.load(f)
            print(f"  ✓ {fname} (Mondrian)")
            break
        except Exception as e:
            print(f"  ⚠ {fname} — {e}")

    # Cargar cuantiles por grupo
    q_per_group = None
    for fname in ["mondrian_q_per_group_v2.pkl", "mondrian_q_per_group.pkl", "q_per_group.npy"]:
        try:
            fpath = MODELS_DIR / fname
            if fname.endswith(".npy"):
                q_per_group = np.load(fpath, allow_pickle=True)
            else:
                with open(fpath, "rb") as f:
                    q_per_group = pickle.load(f)
            print(f"  ✓ {fname} (q_per_group)")
            break
        except Exception as e:
            print(f"  ⚠ {fname} — {e}")

    # ── 2. Cargar datos de test ────────────────────────────────────────────
    print("\n📊 Cargando datos de test...")
    try:
        test_df = pd.read_csv(DATA_DIR / "test.csv")
        print(f"  ✓ test.csv — {len(test_df):,} filas × {test_df.shape[1]} columnas")
        print(f"  Columnas: {list(test_df.columns[:10])}{'...' if len(test_df.columns)>10 else ''}")
    except Exception as e:
        print(f"  ✗ test.csv — {e}")
        return None

    # ── 3. Intentar cargar predicciones ya guardadas ───────────────────────
    pred_files = [
        "test_predictions_e2c_final_v5.csv",
        "test_predictions_e2c_final_v4.csv",
        "test_predictions_e2c_final.csv",
        "test_predictions_FINAL.csv",
        "test_predictions_e2c_v2.csv",
        "test_predictions_e2c.csv",
    ]

    preds_df = None
    for fname in pred_files:
        fpath = MODELS_DIR / fname
        if fpath.exists():
            try:
                preds_df = pd.read_csv(fpath)
                print(f"\n  ✓ Predicciones cargadas: {fname}")
                print(f"    Columnas: {list(preds_df.columns)}")
                break
            except Exception as e:
                print(f"  ⚠ {fname} — {e}")

    # ── 4. Calcular métricas ───────────────────────────────────────────────
    print("\n📐 Calculando métricas...")
    results_oe3 = {}

    if preds_df is not None:
        # Detectar columnas automáticamente
        col_true  = next((c for c in preds_df.columns if "true" in c.lower() or "real" in c.lower() or "y_true" in c.lower()), None)
        col_pred  = next((c for c in preds_df.columns if "pred" in c.lower() and "lower" not in c.lower() and "upper" not in c.lower()), None)
        col_lower = next((c for c in preds_df.columns if "lower" in c.lower() or "low" in c.lower()), None)
        col_upper = next((c for c in preds_df.columns if "upper" in c.lower() or "high" in c.lower()), None)

        if col_true and col_pred:
            y_true = preds_df[col_true].dropna().values
            y_pred = preds_df[col_pred][:len(y_true)].values

            m = mape(y_true, y_pred)
            s = smape(y_true, y_pred)
            r = rmse(y_true, y_pred)
            r2_score = r2(y_true, y_pred)

            results_oe3["mape"]  = round(m, 4)
            results_oe3["smape"] = round(s, 4)
            results_oe3["rmse"]  = round(r, 4)
            results_oe3["r2"]    = round(r2_score, 4)
            results_oe3["n_test"] = len(y_true)

            print(f"\n  {'Métrica':<20} {'Valor':>10}  {'Meta':>12}  {'Estado'}")
            print(f"  {'-'*55}")
            print(f"  {'MAPE':<20} {m:>9.4f}%  {'< 1%':>12}  {status(m < 1.0, 'OE3 MAPE')}")
            print(f"  {'SMAPE':<20} {s:>9.4f}%  {'referencia':>12}")
            print(f"  {'RMSE':<20} {r:>10.4f}  {'referencia':>12}")
            print(f"  {'R²':<20} {r2_score:>10.4f}  {'> 0.85':>12}  {status(r2_score > 0.85, 'R²')}")
            print(f"  {'N test':<20} {len(y_true):>10,}")

            # Intervalos Mondrian
            if col_lower and col_upper:
                lower = preds_df[col_lower][:len(y_true)].values
                upper = preds_df[col_upper][:len(y_true)].values
                cov   = coverage(y_true, lower, upper)
                width = interval_width(lower, upper)
                results_oe3["coverage"] = round(cov, 2)
                results_oe3["interval_width"] = round(width, 4)
                print(f"\n  {'Cobertura Mondrian':<20} {cov:>9.2f}%  {'93–97%':>12}  {status(93 <= cov <= 97, 'Cobertura')}")
                print(f"  {'Ancho intervalo':<20} {width:>10.4f}  {'referencia':>12}")
            else:
                print("\n  ⚠ No se encontraron columnas de intervalos (lower/upper)")
        else:
            print(f"  ⚠ No se detectaron columnas y_true/y_pred automáticamente")
            print(f"    Columnas disponibles: {list(preds_df.columns)}")
    else:
        print("  ⚠ No se encontraron archivos de predicciones guardadas")
        print("    → Ejecuta primero el pipeline de entrenamiento para generar predicciones")

    # Cargar resultados previos de PE3 si existen
    pe3_json = MODELS_DIR / "pe3_results_final.json"
    if pe3_json.exists():
        try:
            with open(pe3_json) as f:
                pe3_data = json.load(f)
            print(f"\n  📄 pe3_results_final.json encontrado:")
            for k, v in pe3_data.items():
                print(f"    {k}: {v}")
            results_oe3["pe3_results"] = pe3_data
        except Exception as e:
            print(f"  ⚠ No se pudo leer pe3_results_final.json — {e}")

    return results_oe3

# ══════════════════════════════════════════════════════════════════════════════
# OE4 — BERT/E5 Detección de Obsolescencia
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_oe4():
    print_section("OE4 — Detección de Obsolescencia (BERT/E5)")
    print("  Meta: F1_macro > 0.93 | Clases: Vigente / Transición / Obsoleto\n")

    bert_dir = MODELS_DIR / "pe4_bert_obsolescence"
    if not bert_dir.exists():
        print(f"  ✗ Directorio no encontrado: {bert_dir}")
        return None

    print(f"  ✓ Directorio encontrado: {bert_dir}")
    files = list(bert_dir.iterdir())
    print(f"  Archivos ({len(files)}):")
    for f in sorted(files):
        size_mb = f.stat().st_size / 1e6
        print(f"    - {f.name:<40} {size_mb:>8.2f} MB")

    # ── 1. Buscar resultados de evaluación guardados ───────────────────────
    results_oe4 = {}
    eval_files = [
        bert_dir / "eval_results.json",
        bert_dir / "trainer_state.json",
        bert_dir / "all_results.json",
        bert_dir / "test_results.json",
        ROOT / "scripts" / "pe4_eval_results.json",
    ]

    eval_data = None
    for ef in eval_files:
        if ef.exists():
            try:
                with open(ef) as f:
                    eval_data = json.load(f)
                print(f"\n  ✓ Resultados encontrados: {ef.name}")
                break
            except Exception as e:
                print(f"  ⚠ {ef.name} — {e}")

    if eval_data:
        print("\n  📊 Métricas guardadas:")
        for k, v in eval_data.items():
            if isinstance(v, (int, float)):
                print(f"    {k:<35} {v:.4f}")
        
        # Buscar F1_macro
        f1_keys = [k for k in eval_data if "f1" in k.lower() or "macro" in k.lower()]
        if f1_keys:
            for k in f1_keys:
                v = eval_data[k]
                results_oe4[k] = v
                if "macro" in k.lower():
                    print(f"\n  {'F1_macro':<20} {v:>10.4f}  {'> 0.93':>12}  {status(v > 0.93, 'OE4 F1_macro')}")
    else:
        print("\n  ⚠ No se encontraron archivos de métricas guardadas")
        print("    → Intentando inferencia rápida con el modelo...")

        # ── 2. Intentar cargar modelo y hacer inferencia rápida ────────────
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            import torch

            print("\n  📦 Cargando modelo desde disco...")
            tokenizer = AutoTokenizer.from_pretrained(str(bert_dir))
            model = AutoModelForSequenceClassification.from_pretrained(str(bert_dir))
            model.eval()
            print(f"  ✓ Modelo cargado — Labels: {model.config.id2label}")

            # Ejemplos de prueba rápida
            test_texts = [
                "Intel Core i9-14900K procesador de última generación",
                "AMD Ryzen 5 3600 — sucesor ya disponible: Ryzen 5 5600",
                "Intel Core i7-7700K descontinuado, sin soporte",
                "NVIDIA RTX 4090 GPU flagship 2024",
                "DDR3 RAM 8GB — tecnología obsoleta, reemplazada por DDR4/DDR5",
            ]

            print("\n  🧪 Inferencia rápida (5 ejemplos):")
            print(f"  {'Texto':<50} {'Predicción':<15} {'Confianza'}")
            print(f"  {'-'*80}")

            label_names = {0: "Vigente", 1: "Transición", 2: "Obsoleto"}
            if hasattr(model.config, 'id2label') and model.config.id2label:
                label_names = {int(k): v for k, v in model.config.id2label.items()}

            with torch.no_grad():
                for text in test_texts:
                    inputs = tokenizer(
                        text, return_tensors="pt",
                        truncation=True, max_length=128, padding=True
                    )
                    outputs = model(**inputs)
                    probs = torch.softmax(outputs.logits, dim=-1)[0]
                    pred_id = probs.argmax().item()
                    conf = probs[pred_id].item()
                    label = label_names.get(pred_id, f"clase_{pred_id}")
                    texto_corto = text[:47] + "..." if len(text) > 47 else text
                    print(f"  {texto_corto:<50} {label:<15} {conf:.3f}")

            results_oe4["inference_ok"] = True
            results_oe4["num_labels"] = model.config.num_labels
            results_oe4["label_map"] = label_names

        except ImportError:
            print("  ⚠ transformers/torch no disponible en este entorno")
            print("    → Usa: pip install transformers torch")
        except Exception as e:
            print(f"  ✗ Error al cargar modelo: {e}")

    return results_oe4

# ══════════════════════════════════════════════════════════════════════════════
# RESUMEN FINAL
# ══════════════════════════════════════════════════════════════════════════════

def print_summary(results_oe3, results_oe4):
    print_section("RESUMEN EJECUTIVO — Estado de la Tesis")

    print("""
┌─────────────────────────────────────────────────────────────┐
│  TESIS: Sistema Híbrido DL + Computación Evolutiva          │
│  Autor: Kotska Rony Pariona Martinez | UNI-FIIS             │
│  HuggingFace: kotska-pariona/tesis-bert-obsolescence        │
└─────────────────────────────────────────────────────────────┘
""")

    # OE3
    print("  OE3 — LightGBM + Mondrian:")
    if results_oe3:
        mape_val = results_oe3.get("mape")
        cov_val  = results_oe3.get("coverage")
        r2_val   = results_oe3.get("r2")
        if mape_val is not None:
            print(f"    MAPE:      {mape_val:.4f}%  {status(mape_val < 1.0, 'Meta < 1%')}")
        if r2_val is not None:
            print(f"    R²:        {r2_val:.4f}   {status(r2_val > 0.85, 'Meta > 0.85')}")
        if cov_val is not None:
            print(f"    Cobertura: {cov_val:.2f}%   {status(93 <= cov_val <= 97, 'Meta 93-97%')}")
    else:
        print("    ⚠ Sin resultados — revisar predicciones")

    # OE4
    print("\n  OE4 — BERT/E5 Obsolescencia:")
    if results_oe4:
        f1_val = results_oe4.get("eval_f1_macro") or results_oe4.get("f1_macro") or results_oe4.get("test_f1_macro")
        if f1_val:
            print(f"    F1_macro:  {f1_val:.4f}   {status(f1_val > 0.93, 'Meta > 0.93')}")
        elif results_oe4.get("inference_ok"):
            print(f"    Modelo cargado ✓ | {results_oe4.get('num_labels')} clases")
            print(f"    ⚠ F1_macro no disponible — ejecutar evaluación completa")
        else:
            print("    ⚠ Sin resultados de métricas")
    else:
        print("    ⚠ Sin resultados — revisar modelo")

    # Guardar resultados
    output = {
        "fecha_evaluacion": pd.Timestamp.now().isoformat(),
        "oe3": results_oe3 or {},
        "oe4": results_oe4 or {},
    }
    out_path = RESULTS_DIR / "evaluation_report.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  💾 Reporte guardado en: {out_path}")

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluación de modelos OE3 y OE4")
    parser.add_argument("--only", choices=["oe3", "oe4"], help="Evaluar solo un objetivo")
    args = parser.parse_args()

    results_oe3, results_oe4 = None, None

    if args.only != "oe4":
        results_oe3 = evaluate_oe3()

    if args.only != "oe3":
        results_oe4 = evaluate_oe4()

    print_summary(results_oe3, results_oe4)