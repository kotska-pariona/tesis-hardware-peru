"""
main.py
════════
Orquestador principal del pipeline de ROI de importación.

Modos de ejecución:
  python main.py                    → Pipeline completo
  python main.py --only scrape      → Solo scrapear
  python main.py --only merge       → Solo mergear CSVs existentes
  python main.py --only roi         → Solo calcular ROI
  python main.py --sources-import amazon ebay --categories CPU GPU
  python main.py --dry-run          → Sin escribir nada

Flujo completo:
  [1] Actualizar tipo de cambio USD/PEN
  [2] Scraper local PE  (Falabella / Ripley / Hiraoka)
  [3] Scraper importación (Amazon / AliExpress / eBay)
  [4] Merge + normalización
  [5] Cálculo de ROI
  [6] Reporte de oportunidades
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

from config import (
    LOG_LEVEL, LOG_FILE, CATEGORIES,
    SOURCES_LOCAL, SOURCES_IMPORT,
    DATA_DIR, OPORTUNIDADES_CSV,
)

# ── Logging con archivo ───────────────────────────────────────────────────────
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("main")

# ══════════════════════════════════════════════════════════════════════════════
# STEPS DEL PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def step_dolar() -> float:
    """Step 1: Actualizar tipo de cambio"""
    _banner("STEP 1 — Tipo de cambio USD/PEN")
    from scraper_dolar import get_usd_pen
    rate = get_usd_pen(force_update=True)
    log.info(f"  USD/PEN venta = S/ {rate['usd_pen_venta']} (fuente: {rate['source']})")
    return rate["usd_pen_venta"]

def step_scrape_local(
    batch_id: str,
    sources: list,
    categories: list,
    dry_run: bool = False,
) -> dict:
    """Step 2: Scraper local PE"""
    _banner("STEP 2 — Scraper Local PE (Falabella / Ripley / Hiraoka)")
    try:
        from scraper_local import run_local
        csv_path, total, stats = run_local(
            batch_id=batch_id,
            sources=sources,
            categories=categories,
            dry_run=dry_run,
        )
        log.info(f"  ✅ Local PE: {total} items → {csv_path}")
        return {"status": "ok", "total": total, "path": str(csv_path), "stats": stats}
    except ImportError:
        log.warning("  ⚠️  scraper_local.py no encontrado — saltando step")
        return {"status": "skipped", "total": 0}
    except Exception as e:
        log.error(f"  ❌ Error en scraper local: {e}")
        return {"status": "error", "total": 0, "error": str(e)}

def step_scrape_import(
    batch_id: str,
    sources: list,
    categories: list,
    dry_run: bool = False,
) -> dict:
    """Step 3: Scraper de importación"""
    _banner("STEP 3 — Scraper Importación (Amazon / AliExpress / eBay)")
    try:
        from scraper_importacion import run_importacion
        csv_path, total, stats = run_importacion(
            batch_id=batch_id,
            sources=sources,
            categories=categories,
            dry_run=dry_run,
        )
        log.info(f"  ✅ Importación: {total} items → {csv_path}")
        return {"status": "ok", "total": total, "path": str(csv_path), "stats": stats}
    except ImportError:
        log.warning("  ⚠️  scraper_importacion.py no encontrado — saltando step")
        return {"status": "skipped", "total": 0}
    except Exception as e:
        log.error(f"  ❌ Error en scraper importación: {e}")
        return {"status": "error", "total": 0, "error": str(e)}

def step_merge(batch_id: str) -> dict:
    """Step 4: Merge y normalización"""
    _banner("STEP 4 — Merge y Normalización")
    try:
        from merger import merge
        df = merge(batch_id=batch_id, save=True)
        if df.empty:
            log.warning("  ⚠️  Merge resultó vacío")
            return {"status": "empty", "total": 0, "df": None}
        log.info(f"  ✅ Merge: {len(df)} registros totales")
        return {"status": "ok", "total": len(df), "df": df}
    except Exception as e:
        log.error(f"  ❌ Error en merge: {e}")
        return {"status": "error", "total": 0, "df": None, "error": str(e)}

def step_roi(df=None) -> dict:
    """Step 5: Cálculo de ROI"""
    _banner("STEP 5 — Cálculo de ROI")
    try:
        from roi_calculator import analyze_dataframe, top_oportunidades
        from merger import get_comparison_df

        if df is None:
            df = get_comparison_df()

        if df is None or df.empty:
            log.warning("  ⚠️  Sin datos para calcular ROI")
            return {"status": "empty", "total": 0}

        df_roi = analyze_dataframe(df, save=True)

        if df_roi.empty:
            return {"status": "empty", "total": 0}

        # Mostrar top 10 oportunidades en log
        top = top_oportunidades(n=10)
        if not top.empty:
            log.info(f"\n  🏆 TOP 10 OPORTUNIDADES DE IMPORTACIÓN:")
            log.info(f"  {'Categoría':<12} {'ROI':>7} {'Ahorro':>10} {'Título':<40}")
            log.info(f"  {'-'*75}")
            for _, row in top.iterrows():
                log.info(
                    f"  {str(row['category']):<12} "
                    f"{float(row['roi_pct']):>6.1f}% "
                    f"S/{float(row['ahorro_pen']):>8.2f}  "
                    f"{str(row['title'])[:40]}"
                )

        conviene_count = int(df_roi["conviene_importar"].sum())
        return {
            "status":          "ok",
            "total":           len(df_roi),
            "conviene":        conviene_count,
            "mejor_roi":       float(df_roi["roi_pct"].max()),
            "mejor_ahorro":    float(df_roi["ahorro_pen"].max()),
            "df_roi":          df_roi,
        }
    except Exception as e:
        log.error(f"  ❌ Error en ROI: {e}")
        return {"status": "error", "total": 0, "error": str(e)}

# ══════════════════════════════════════════════════════════════════════════════
# REPORTE FINAL
# ══════════════════════════════════════════════════════════════════════════════

def print_summary(batch_id: str, start_ts: float, results: dict):
    elapsed = time.time() - start_ts
    mins    = int(elapsed // 60)
    secs    = int(elapsed % 60)

    log.info("\n" + "═"*60)
    log.info("  RESUMEN DEL PIPELINE")
    log.info("═"*60)
    log.info(f"  Batch ID     : {batch_id}")
    log.info(f"  Duración     : {mins}m {secs}s")
    log.info(f"  USD/PEN      : S/ {results.get('usd_pen', 'N/A')}")
    log.info("")

    r_local  = results.get("local",  {})
    r_import = results.get("import", {})
    r_merge  = results.get("merge",  {})
    r_roi    = results.get("roi",    {})

    log.info(f"  {'Step':<25} {'Estado':<10} {'Items':>8}")
    log.info(f"  {'-'*45}")
    log.info(f"  {'Scraper Local PE':<25} {r_local.get('status','—'):<10} {r_local.get('total',0):>8,}")
    log.info(f"  {'Scraper Importación':<25} {r_import.get('status','—'):<10} {r_import.get('total',0):>8,}")
    log.info(f"  {'Merge':<25} {r_merge.get('status','—'):<10} {r_merge.get('total',0):>8,}")
    log.info(f"  {'Análisis ROI':<25} {r_roi.get('status','—'):<10} {r_roi.get('total',0):>8,}")

    if r_roi.get("status") == "ok":
        log.info("")
        log.info(f"  Oportunidades encontradas : {r_roi.get('conviene', 0)}")
        log.info(f"  Mejor ROI                 : {r_roi.get('mejor_roi', 0):.1f}%")
        log.info(f"  Mejor ahorro              : S/ {r_roi.get('mejor_ahorro', 0):.2f}")
        log.info(f"  CSV oportunidades         : {OPORTUNIDADES_CSV}")

    log.info("═"*60)

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _banner(title: str):
    log.info("\n" + "█"*60)
    log.info(f"  {title}")
    log.info("█"*60)

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Pipeline de ROI de importación PE",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--only",
        choices=["scrape", "scrape-local", "scrape-import", "merge", "roi"],
        default=None,
        help=(
            "Ejecutar solo un step:\n"
            "  scrape        → ambos scrapers\n"
            "  scrape-local  → solo Falabella/Ripley/Hiraoka\n"
            "  scrape-import → solo Amazon/AliExpress/eBay\n"
            "  merge         → solo merge de CSVs existentes\n"
            "  roi           → solo cálculo de ROI"
        ),
    )
    parser.add_argument(
        "--sources-local",
        nargs="+",
        default=SOURCES_LOCAL,
        choices=["falabella", "ripley", "hiraoka"],
        help="Fuentes locales PE a scrapear",
    )
    parser.add_argument(
        "--sources-import",
        nargs="+",
        default=SOURCES_IMPORT,
        choices=["amazon", "aliexpress", "ebay"],
        help="Fuentes de importación a scrapear",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=CATEGORIES,
        choices=CATEGORIES,
        help="Categorías a procesar",
    )
    parser.add_argument(
        "--batch-id",
        default=None,
        help="Batch ID manual (default: timestamp automático)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parsear sin escribir CSV ni calcular ROI",
    )
    parser.add_argument(
        "--skip-dolar",
        action="store_true",
        help="Saltar actualización de tipo de cambio",
    )
    return parser.parse_args()

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    args     = _parse_args()
    start_ts = time.time()
    batch_id = args.batch_id or datetime.now().strftime("%Y%m%d_%H%M%S")

    log.info("═"*60)
    log.info("  PIPELINE ROI IMPORTACIÓN PE — INICIO")
    log.info("═"*60)
    log.info(f"  Batch ID    : {batch_id}")
    log.info(f"  Modo        : {args.only or 'completo'}")
    log.info(f"  Categorías  : {', '.join(args.categories)}")
    log.info(f"  Src Local   : {', '.join(args.sources_local)}")
    log.info(f"  Src Import  : {', '.join(args.sources_import)}")
    log.info(f"  Dry-run     : {args.dry_run}")
    log.info("═"*60)

    results = {}
    only    = args.only

    # ── Step 1: Tipo de cambio ────────────────────────────────────────────────
    if not args.skip_dolar and only not in ("scrape", "scrape-local", "scrape-import"):
        results["usd_pen"] = step_dolar()
    elif not args.skip_dolar:
        results["usd_pen"] = step_dolar()

    # ── Step 2: Scraper local ─────────────────────────────────────────────────
    if only in (None, "scrape", "scrape-local"):
        results["local"] = step_scrape_local(
            batch_id=batch_id,
            sources=args.sources_local,
            categories=args.categories,
            dry_run=args.dry_run,
        )
    else:
        results["local"] = {"status": "skipped", "total": 0}

    # ── Step 3: Scraper importación ───────────────────────────────────────────
    if only in (None, "scrape", "scrape-import"):
        results["import"] = step_scrape_import(
            batch_id=batch_id,
            sources=args.sources_import,
            categories=args.categories,
            dry_run=args.dry_run,
        )
    else:
        results["import"] = {"status": "skipped", "total": 0}

    # ── Step 4: Merge ─────────────────────────────────────────────────────────
    if only in (None, "merge") and not args.dry_run:
        results["merge"] = step_merge(batch_id=batch_id)
    elif only == "merge":
        results["merge"] = step_merge(batch_id=batch_id)
    else:
        results["merge"] = {"status": "skipped", "total": 0, "df": None}

    # ── Step 5: ROI ───────────────────────────────────────────────────────────
    df_merged = results.get("merge", {}).get("df", None)
    if only in (None, "roi") and not args.dry_run:
        results["roi"] = step_roi(df=df_merged)
    elif only == "roi":
        results["roi"] = step_roi(df=None)  # carga desde CSV
    else:
        results["roi"] = {"status": "skipped", "total": 0}

    # ── Resumen ───────────────────────────────────────────────────────────────
    print_summary(batch_id, start_ts, results)

    # Exit code: 0 si todo OK o skipped, 1 si algún step falló
    failed = [k for k, v in results.items()
              if isinstance(v, dict) and v.get("status") == "error"]
    if failed:
        log.error(f"  Steps con error: {failed}")
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
