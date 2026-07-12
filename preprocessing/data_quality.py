#!/usr/bin/env python3
"""
run_pipeline.py — Orquestador Maestro del Sistema Completo v1.0
════════════════════════════════════════════════════════════════════
Ejecuta las 5 etapas del sistema (Fig. 4.1 del plan de tesis):

  Etapa I    → agent/main.py            (recolección: MercadoLibre + Trends)
  Etapa I.b  → preprocessing/data_quality.py  (auditoría, outliers)
  Etapa II   → preprocessing/feature_engineering.py (MICE, rolling z-score)
  Etapa III  → models/ (TFT+TCN ensemble, XGBoost, BERT, MAPIE)
  Etapa IV   → optimization/nsga3_portfolio.py (NSGA-III)
  Etapa V    → decision/decision_engine.py (BUY/WAIT/LIQUIDATE)

Este script NO reemplaza a agent/main.py — lo INVOCA como Etapa I.
Diseñado para ejecución batch nocturna (00:00-02:00 UTC-5), acorde
a la Sección 4.7.1 del plan de tesis. Latencia estimada total:
~8-12 min de inferencia (500 SKUs, GPU A100) + tiempo de scraping.

NOTA IMPORTANTE — Entrenamiento vs. Inferencia:
  Este orquestador ejecuta el pipeline en modo INFERENCIA (usa modelos
  ya entrenados y serializados en ONNX/pickle). El ENTRENAMIENTO de
  TFT, TCN, XGBoost y BERT es un proceso separado (notebooks / jobs
  de GPU, Fase II del cronograma, semanas 5-9), ejecutado manualmente
  o vía workflow independiente (train_models.yml), NO en este script.
"""

import sys
import subprocess
import logging
import logging.handlers
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT_DIR   = Path(__file__).resolve().parent
DATA_DIR   = ROOT_DIR / "data" / "raw"
MODELS_DIR = ROOT_DIR / "models" / "artifacts"   # modelos entrenados (.onnx/.pkl)
LOG_DIR    = ROOT_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_file_handler = logging.handlers.RotatingFileHandler(
    str(LOG_DIR / "pipeline_master.log"),
    maxBytes=5 * 1024 * 1024, backupCount=7, encoding="utf-8",
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), _file_handler],
)
log = logging.getLogger("pipeline_master")


# ══════════════════════════════════════════════════════════════════
# UTILIDAD: ejecutar sub-etapas como subprocesos independientes
# (aísla fallos: si TFT falla, XGBoost y BERT igual pueden correr)
# ══════════════════════════════════════════════════════════════════
def _run_stage(label: str, cmd: list, critical: bool = False) -> bool:
    log.info(f"\n{'='*60}\n▶ {label}\n{'='*60}")
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600
        )
        elapsed = time.time() - t0
        if result.returncode == 0:
            log.info(f"  ✅ {label} completado ({elapsed:.0f}s)")
            return True
        else:
            log.error(f"  ❌ {label} falló (rc={result.returncode})")
            log.error(f"     stderr: {result.stderr[-500:]}")
            if critical:
                raise RuntimeError(f"Etapa crítica falló: {label}")
            return False
    except subprocess.TimeoutExpired:
        log.error(f"  ⏱ {label} excedió timeout (3600s)")
        if critical:
            raise
        return False
    except Exception as e:
        log.error(f"  ❌ {label} error inesperado: {e}")
        if critical:
            raise
        return False


# ══════════════════════════════════════════════════════════════════
# ETAPA I — Recolección (delega en agent/main.py, YA EXISTENTE)
# ══════════════════════════════════════════════════════════════════
def stage_1_collection(batch_id: str, mode: str = "normal") -> bool:
    return _run_stage(
        "Etapa I — Recolección de datos",
        [
            "python", str(ROOT_DIR / "agent" / "main.py"),
            "--mode", mode, "--batch-id", batch_id,
        ],
        critical=True,   # sin datos, no hay pipeline
    )


# ══════════════════════════════════════════════════════════════════
# ETAPA I.b — Calidad de datos (data_quality.py, YA EXISTENTE v1.0)
# ══════════════════════════════════════════════════════════════════
def stage_1b_quality(batch_id: str) -> bool:
    return _run_stage(
        "Etapa I.b — Auditoría y limpieza de calidad",
        [
            "python", str(ROOT_DIR / "preprocessing" / "data_quality.py"),
            "--input", str(DATA_DIR / "MASTER_hardware_peru.csv"),
            "--batch-id", batch_id,
        ],
        critical=True,   # sin dataset limpio, los modelos fallan
    )


# ══════════════════════════════════════════════════════════════════
# ETAPA II — Feature Engineering (MICE + rolling z-score)
# ══════════════════════════════════════════════════════════════════
def stage_2_features(batch_id: str) -> bool:
    return _run_stage(
        "Etapa II — Ingeniería de características",
        [
            "python", str(ROOT_DIR / "preprocessing" / "feature_engineering.py"),
            "--batch-id", batch_id,
        ],
        critical=True,
    )


# ══════════════════════════════════════════════════════════════════
# ETAPA III — Inferencia de modelos (TFT+TCN, XGBoost, BERT, MAPIE)
# Cada módulo corre en paralelo lógico (independiente entre sí);
# si BERT falla, el sistema sigue con riesgo_obsolescencia = None
# y el decision_engine usa la rama por defecto (WAIT).
# ══════════════════════════════════════════════════════════════════
def stage_3_inference(batch_id: str) -> dict:
    results = {}

    results["demanda"] = _run_stage(
        "Etapa III.a — Ensemble TFT+TCN (demanda)",
        ["python", str(ROOT_DIR / "models" / "demand" / "ensemble_stacker.py"),
         "--batch-id", batch_id, "--models-dir", str(MODELS_DIR)],
    )

    results["precio"] = _run_stage(
        "Etapa III.b — XGBoost (precios USD)",
        ["python", str(ROOT_DIR / "models" / "price" / "xgboost_price.py"),
         "--batch-id", batch_id, "--models-dir", str(MODELS_DIR)],
    )

    results["obsolescencia"] = _run_stage(
        "Etapa III.c — BERT (riesgo de obsolescencia)",
        ["python", str(ROOT_DIR / "models" / "obsolescence" / "bert_classifier.py"),
         "--batch-id", batch_id, "--models-dir", str(MODELS_DIR)],
    )

    results["incertidumbre"] = _run_stage(
        "Etapa III.d — MAPIE (calibración IC 95%)",
        ["python", str(ROOT_DIR / "models" / "uncertainty" / "mapie_calibrator.py"),
         "--batch-id", batch_id],
    )

    return results


# ══════════════════════════════════════════════════════════════════
# ETAPA IV — Optimización de portafolio (NSGA-III)
# ══════════════════════════════════════════════════════════════════
def stage_4_optimization(batch_id: str) -> bool:
    return _run_stage(
        "Etapa IV — NSGA-III (frente de Pareto del portafolio)",
        [
            "python", str(ROOT_DIR / "optimization" / "nsga3_portfolio.py"),
            "--batch-id", batch_id,
            "--pop", "200", "--gen", "500",   # Ec. (3.19)-(3.20)
        ],
        critical=True,
    )


# ══════════════════════════════════════════════════════════════════
# ETAPA V — Motor de decisión BUY/WAIT/LIQUIDATE
# ══════════════════════════════════════════════════════════════════
def stage_5_decision(batch_id: str) -> bool:
    return _run_stage(
        "Etapa V — Motor de decisión (Ec. 4.4)",
        [
            "python", str(ROOT_DIR / "decision" / "decision_engine.py"),
            "--batch-id", batch_id,
            "--delta", "0.05", "--rho-threshold", "0.65",
        ],
        critical=True,
    )


# ══════════════════════════════════════════════════════════════════
# POST: refrescar caché de la API para que el dashboard/API sirvan
# las señales nuevas sin reiniciar el proceso FastAPI
# ══════════════════════════════════════════════════════════════════
def refresh_api_cache(batch_id: str) -> bool:
    return _run_stage(
        "Post — Refresh de caché API/Dashboard",
        ["curl", "-X", "POST", "http://localhost:8000/internal/refresh",
         "-H", f"X-Batch-Id: {batch_id}"],
    )


# ══════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL — orquesta las 5 etapas end-to-end
# ══════════════════════════════════════════════════════════════════
def run_full_pipeline(mode: str = "normal"):
    tz_pe    = ZoneInfo("America/Lima")
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    start    = time.time()

    log.info("█" * 60)
    log.info(f"  SISTEMA HÍBRIDO — Pipeline Completo v1.0")
    log.info(f"  Batch: {batch_id} | Hora Lima: "
              f"{datetime.now(tz_pe).strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("█" * 60)

    status = {"batch_id": batch_id, "etapas": {}}

    # Etapa I y I.b son críticas — si fallan, se aborta el batch completo
    status["etapas"]["I_recoleccion"]   = stage_1_collection(batch_id, mode)
    status["etapas"]["Ib_calidad"]      = stage_1b_quality(batch_id)

    # Etapa II es crítica — los modelos necesitan features
    status["etapas"]["II_features"]     = stage_2_features(batch_id)

    # Etapa III — cada módulo es independiente (falla parcial tolerada)
    status["etapas"]["III_inferencia"]  = stage_3_inference(batch_id)

    # Etapa IV — crítica: sin frente de Pareto no hay decisión
    status["etapas"]["IV_optimizacion"] = stage_4_optimization(batch_id)

    # Etapa V — genera las señales finales BUY/WAIT/LIQUIDATE
    status["etapas"]["V_decision"]      = stage_5_decision(batch_id)

    # Post-proceso
    status["etapas"]["refresh_api"]     = refresh_api_cache(batch_id)

    elapsed = time.time() - start
    status["elapsed_s"] = round(elapsed, 1)

    report_path = DATA_DIR / f"pipeline_report_{batch_id}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)

    log.info("\n" + "█" * 60)
    log.info(f"  PIPELINE COMPLETO — Duración: "
              f"{int(elapsed//60)}m {int(elapsed%60)}s")
    log.info(f"  Reporte: {report_path.name}")
    log.info("█" * 60)

    return status


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Orquestador maestro del sistema híbrido completo"
    )
    parser.add_argument("--mode", default="normal")
    args = parser.parse_args()
    run_full_pipeline(mode=args.mode)
