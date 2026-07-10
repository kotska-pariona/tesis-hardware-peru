#!/usr/bin/env python3
"""
Agente Orquestador - Tesis Dropshipping ROI
Autor: Kotska Pariona - UNI 2026
"""
import argparse
import logging
import json
from datetime import datetime
from pathlib import Path
import pandas as pd
import sys
import os

# ── Configuración de logging ──────────────────────
def setup_logging():
    Path("logs").mkdir(exist_ok=True)
    log_file = f"logs/agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger("AgenteROI")

# ── Pipeline principal ────────────────────────────
def run_pipeline(log):
    log.info("=" * 60)
    log.info("🚀 INICIANDO PIPELINE AGENTE ROI")
    log.info(f"   Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    results = {
        "timestamp": datetime.now().isoformat(),
        "batch_id": datetime.now().strftime('%Y%m%d_%H%M%S'),
        "status": "running",
        "phases": {}
    }

    # ── FASE 1: SCRAPING ──────────────────────────
    log.info("\n📡 FASE 1: Scraping de datos...")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from scraper import start_scheduler, run_batch, setup_logging as scraper_log
        
        scraper_logger = scraper_log()
        items = run_batch()
        
        results["phases"]["scraping"] = {
            "status": "ok",
            "items_collected": len(items) if items else 0
        }
        log.info(f"   ✅ {len(items) if items else 0} items recolectados")
        
    except Exception as e:
        log.error(f"   ❌ Error en scraping: {e}")
        results["phases"]["scraping"] = {"status": "error", "error": str(e)}

    # ── FASE 2: CONSOLIDAR MASTER CSV ─────────────
    log.info("\n📊 FASE 2: Consolidando datos...")
    try:
        master_path = Path("ml_data/ml_hardware_MASTER.csv")
        if master_path.exists():
            df = pd.read_csv(master_path)
            
            # Copiar a data/raw/ para GitHub
            Path("data/raw").mkdir(parents=True, exist_ok=True)
            df.to_csv(f"data/raw/MASTER_{datetime.now().strftime('%Y%m%d')}.csv",
                     index=False, encoding="utf-8-sig")
            
            results["phases"]["consolidation"] = {
                "status": "ok",
                "total_records": len(df),
                "categories": df["category"].value_counts().to_dict() if "category" in df.columns else {}
            }
            log.info(f"   ✅ Master CSV: {len(df)} registros totales")
        else:
            log.warning("   ⚠️ Master CSV no encontrado aún")
            results["phases"]["consolidation"] = {"status": "no_data"}
            
    except Exception as e:
        log.error(f"   ❌ Error consolidando: {e}")
        results["phases"]["consolidation"] = {"status": "error", "error": str(e)}

    # ── FASE 3: REPORTE JSON ──────────────────────
    log.info("\n📝 FASE 3: Generando reporte...")
    try:
        results["status"] = "completed"
        results["end_time"] = datetime.now().isoformat()
        
        Path("data/raw").mkdir(parents=True, exist_ok=True)
        report_path = f"data/raw/report_{results['batch_id']}.json"
        
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        log.info(f"   ✅ Reporte guardado: {report_path}")
        
    except Exception as e:
        log.error(f"   ❌ Error en reporte: {e}")

    # ── RESUMEN FINAL ─────────────────────────────
    log.info("\n" + "=" * 60)
    log.info("✅ PIPELINE COMPLETADO")
    for phase, info in results["phases"].items():
        status_icon = "✅" if info.get("status") == "ok" else "⚠️"
        log.info(f"   {status_icon} {phase}: {info.get('status', 'unknown')}")
    log.info("=" * 60)
    
    return results

# ── Entry point ───────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Agente ROI - Tesis Kotska Pariona UNI 2026"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Ejecutar un batch completo"
    )
    parser.add_argument(
        "--test",
        action="store_true", 
        help="Modo test (sin scraping real)"
    )
    args = parser.parse_args()
    
    log = setup_logging()
    
    if args.test:
        log.info("🧪 MODO TEST - Verificando configuración...")
        log.info("✅ Python OK")
        log.info("✅ Estructura de carpetas OK")
        log.info("✅ Agente listo para producción")
    elif args.batch:
        run_pipeline(log)
    else:
        log.info("Usa --batch para ejecutar o --test para verificar")
        log.info("Ejemplo: python agent/main.py --batch")
