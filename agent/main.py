#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orquestador Principal - Agente ROI Hardware Peru
Autor: Kotska Rony Pariona Martinez - UNI 2026
Version: v2.4 — bugfix: BatchOrchestrator(max_pages), NameError pandas, clean_price
"""

import argparse
import logging
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
    HAS_PANDAS = True
    PANDAS_VERSION = pd.__version__
except ImportError:
    HAS_PANDAS = False
    PANDAS_VERSION = "no instalado"          # ← FIX #3: evita NameError

BASE_DIR   = Path(__file__).parent.parent
DATA_DIR   = BASE_DIR / "data" / "raw"
LOG_DIR    = BASE_DIR / "logs"
MASTER_CSV = DATA_DIR / "MASTER_hardware_peru.csv"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
def setup_logging() -> logging.Logger:
    log_file = LOG_DIR / f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    fmt      = "%(asctime)s [%(levelname)s] %(message)s"
    logger   = logging.getLogger("AgenteROI")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt))
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter(fmt))
        logger.addHandler(fh)
        logger.addHandler(sh)
        logger.propagate = False
    return logger

# ─────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ─────────────────────────────────────────────
def run_pipeline(log: logging.Logger, max_pages: int = 3) -> dict:
    log.info("=" * 60)
    log.info("INICIANDO PIPELINE AGENTE ROI v2.4")
    log.info(f"Fecha     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"DATA_DIR  : {DATA_DIR}")
    log.info(f"Max pages : {max_pages}")
    log.info("=" * 60)

    results = {
        "timestamp" : datetime.now().isoformat(),
        "batch_id"  : datetime.now().strftime("%Y%m%d_%H%M%S"),
        "status"    : "running",
        "phases"    : {},
    }

    # ── FASE 1: Scraping ──────────────────────────
    log.info("FASE 1: Scraping de datos...")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from scraper import BatchOrchestrator

        # ← FIX #1: max_pages va en el constructor, NO en run()
        orch   = BatchOrchestrator(max_pages=max_pages)
        result = orch.run()

        results["phases"]["scraping"] = {
            "status"          : "ok",
            "items_collected" : result.get("items", 0),
            "elapsed_s"       : result.get("elapsed_s", 0),
            "batch_file"      : result.get("batch_file", ""),
        }
        log.info(f"  OK {result.get('items', 0)} items en {result.get('elapsed_s', 0):.1f}s")

    except ImportError as e:
        log.error(f"  ERROR importando scraper: {e}")
        results["phases"]["scraping"] = {"status": "import_error", "error": str(e)}
    except AttributeError as e:
        log.error(f"  ERROR metodo no encontrado: {e}")
        results["phases"]["scraping"] = {"status": "method_error", "error": str(e)}
    except Exception as e:
        log.error(f"  ERROR en scraping: {e}")
        results["phases"]["scraping"] = {"status": "error", "error": str(e)}

    # ── FASE 2: Consolidación ─────────────────────
    log.info("FASE 2: Leyendo Master CSV...")
    try:
        if MASTER_CSV.exists():
            if HAS_PANDAS:
                df = pd.read_csv(MASTER_CSV)
                results["phases"]["consolidation"] = {
                    "status"        : "ok",
                    "total_records" : len(df),
                    "categories"    : df["category"].value_counts().to_dict() if "category" in df.columns else {},
                    "sources"       : df["source"].value_counts().to_dict() if "source" in df.columns else {},
                }
                log.info(f"  OK Master CSV: {len(df)} registros")
            else:
                lines = sum(1 for _ in open(MASTER_CSV, encoding="utf-8")) - 1
                results["phases"]["consolidation"] = {"status": "ok_no_pandas", "total_records": lines}
        else:
            log.warning(f"  AVISO: Master CSV no encontrado en {MASTER_CSV}")
            results["phases"]["consolidation"] = {"status": "no_data"}
    except Exception as e:
        log.error(f"  ERROR consolidando: {e}")
        results["phases"]["consolidation"] = {"status": "error", "error": str(e)}

    # ── FASE 3: Reporte ───────────────────────────
    log.info("FASE 3: Generando reporte...")
    try:
        results["status"]   = "completed"
        results["end_time"] = datetime.now().isoformat()
        report_path = DATA_DIR / f"report_{results['batch_id']}.json"
        report_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"  OK Reporte: {report_path}")
        results["phases"]["report"] = {"status": "ok", "path": str(report_path)}
    except Exception as e:
        log.error(f"  ERROR en reporte: {e}")
        results["phases"]["report"] = {"status": "error", "error": str(e)}

    log.info("=" * 60)
    log.info("PIPELINE COMPLETADO")
    for phase, info in results["phases"].items():
        ok = info.get("status") in ("ok", "ok_no_pandas")
        log.info(f"  [{'OK' if ok else 'WARN'}] {phase}: {info.get('status', 'unknown')}")
    log.info("=" * 60)
    return results

# ─────────────────────────────────────────────
# MODO TEST  (sin sys.exit → no mata el workflow)
# ─────────────────────────────────────────────
def run_test(log: logging.Logger, exit_on_result: bool = True):
    log.info("=" * 50)
    log.info("MODO TEST - Verificando configuracion v2.4")
    log.info("=" * 50)
    errors = []

    log.info(f"BASE_DIR  : {BASE_DIR} ({'OK' if BASE_DIR.exists() else 'NO EXISTE'})")
    log.info(f"DATA_DIR  : {DATA_DIR} ({'OK' if DATA_DIR.exists() else 'CREADO'})")
    log.info(f"LOG_DIR   : {LOG_DIR}  ({'OK' if LOG_DIR.exists() else 'CREADO'})")

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from scraper import BatchOrchestrator, CATEGORIES
        orch    = BatchOrchestrator()
        methods = [m for m in dir(orch) if not m.startswith("_") and callable(getattr(orch, m))]
        log.info(f"scraper.py : OK - BatchOrchestrator importado")
        log.info(f"Metodo run : {'OK' if hasattr(orch, 'run') else 'NO ENCONTRADO'}")
        log.info(f"Metodos    : {methods}")
        log.info(f"Categorias : {list(CATEGORIES.keys())}")
    except ImportError as e:
        log.error(f"scraper.py: ERROR - {e}")
        errors.append(str(e))

    # ← FIX #3: usa PANDAS_VERSION (siempre definida)
    log.info(f"pandas    : {'OK v' + PANDAS_VERSION if HAS_PANDAS else 'NO instalado'}")
    log.info(f"Python    : {sys.version.split()[0]}")
    log.info("=" * 50)

    if errors:
        log.error(f"TEST FALLIDO - {len(errors)} error(es)")
        for e in errors:
            log.error(f"  - {e}")
        if exit_on_result:
            sys.exit(1)
        return False
    else:
        log.info("TEST OK - Sistema listo para produccion")
        if exit_on_result:
            sys.exit(0)
        return True

# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Agente ROI - Tesis Kotska Pariona UNI 2026")
    parser.add_argument("--batch",  action="store_true", help="Ejecutar batch completo")
    parser.add_argument("--test",   action="store_true", help="Verificar configuracion")
    parser.add_argument("--pages",  type=int, default=3,  help="Paginas por categoria")  # ← FIX #2: default=3
    parser.add_argument("--stats",  action="store_true", help="Ver estadisticas")
    args = parser.parse_args()

    log = setup_logging()

    if args.test:
        # exit_on_result=True: comportamiento normal en CLI
        run_test(log, exit_on_result=True)
    elif args.batch:
        result = run_pipeline(log, max_pages=max(1, args.pages))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.stats:
        if MASTER_CSV.exists() and HAS_PANDAS:
            df       = pd.read_csv(MASTER_CSV)
            date_min = df["scraped_at"].dropna().min() if "scraped_at" in df.columns else "N/A"
            date_max = df["scraped_at"].dropna().max() if "scraped_at" in df.columns else "N/A"
            stats    = {
                "total_records" : len(df),
                "categories"    : df["category"].value_counts().to_dict() if "category" in df.columns else {},
                "sources"       : df["source"].value_counts().to_dict() if "source" in df.columns else {},
                "date_range"    : f"{str(date_min)[:10]} -> {str(date_max)[:10]}",
            }
            print(json.dumps(stats, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(
                {"status": "no_data", "path": str(MASTER_CSV)}, indent=2))
    else:
        result = run_pipeline(log, max_pages=args.pages)
        print(json.dumps(result, indent=2, ensure_ascii=False))
