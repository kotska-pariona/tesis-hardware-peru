"""
main.py  v4.0
══════════════
Orquestador principal del pipeline de scraping.
Ejecuta scraper_importacion + scraper_competencia
y consolida todo en master.csv con ROI calculado.

Uso:
  python main.py                        # ejecuta todo
  python main.py --only importacion     # solo fuentes de importación
  python main.py --only competencia     # solo fuentes de competencia
  python main.py --categories CPU GPU   # solo esas categorías
"""

import os, sys, csv, json, logging, argparse
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "data"))
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Importar scrapers ─────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
try:
    from scrapers.scraper_importacion import run_importacion
    from scrapers.scraper_competencia import run_competencia
except ImportError:
    # Si están en la misma carpeta
    from scraper_importacion import run_importacion
    from scraper_competencia import run_competencia

# ── ROI Calculator inline ─────────────────────────────────────────────────────
def calcular_roi(
    price_usd: float,
    shipping_usd: float,
    tipo_cambio: float,
    precio_techo_pen: float,
    arancel_pct: float = 0.18,   # IGV 18%
    ad_valorem_pct: float = 0.0, # 0% para hardware (partida 8471)
    courier_pen: float = 50.0,   # costo courier estimado
    margen_minimo_pct: float = 0.20,
) -> dict:
    """
    Calcula el ROI real de importar un producto y venderlo en Perú.

    Fórmula:
      costo_importacion = (price_usd + shipping_usd) × TC × (1 + arancel + ad_valorem) + courier
      precio_venta_sugerido = precio_techo_pen × 0.90  (10% más barato que competencia)
      margen_neto = precio_venta_sugerido - costo_importacion
      roi = margen_neto / costo_importacion × 100
    """
    if price_usd <= 0 or tipo_cambio <= 0:
        return {"roi_pct": 0, "viable": False, "accion": "DATOS_INSUFICIENTES"}

    costo_fob_pen     = (price_usd + shipping_usd) * tipo_cambio
    tributos_pen      = costo_fob_pen * (arancel_pct + ad_valorem_pct)
    costo_total_pen   = costo_fob_pen + tributos_pen + courier_pen
    precio_venta_pen  = precio_techo_pen * 0.90  # 10% bajo la competencia
    margen_neto_pen   = precio_venta_pen - costo_total_pen
    roi_pct           = (margen_neto_pen / costo_total_pen * 100) if costo_total_pen > 0 else 0

    # Decisión
    if roi_pct >= 30:
        accion = "IMPORTAR_AHORA"
    elif roi_pct >= margen_minimo_pct * 100:
        accion = "IMPORTAR_EVALUAR"
    elif roi_pct >= 0:
        accion = "MARGEN_BAJO"
    else:
        accion = "NO_RENTABLE"

    return {
        "costo_fob_pen":    round(costo_fob_pen, 2),
        "tributos_pen":     round(tributos_pen, 2),
        "costo_total_pen":  round(costo_total_pen, 2),
        "precio_venta_pen": round(precio_venta_pen, 2),
        "margen_neto_pen":  round(margen_neto_pen, 2),
        "roi_pct":          round(roi_pct, 1),
        "viable":           roi_pct >= margen_minimo_pct * 100,
        "accion":           accion,
    }

# ── Consolidar master.csv ─────────────────────────────────────────────────────
def consolidar_master(batch_id: str, tipo_cambio: float):
    """
    Lee importacion_*.csv y competencia_*.csv del batch actual,
    cruza por categoría y calcula ROI para cada item de importación.
    Escribe en data/master.csv
    """
    master_path = OUTPUT_DIR / "master.csv"
    import_path = OUTPUT_DIR / f"importacion_{batch_id}.csv"
    comp_path   = OUTPUT_DIR / f"competencia_{batch_id}.csv"

    # Leer precios techo por categoría (máximo de competencia)
    precios_techo = {}
    if comp_path.exists():
        with open(comp_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cat = row.get("category","")
                try:
                    p = float(row.get("price_pen", 0))
                    if p > precios_techo.get(cat, 0):
                        precios_techo[cat] = p
                except:
                    pass
        log.info(f"Precios techo por categoría: {precios_techo}")

    # Leer items de importación y calcular ROI
    master_fields = [
        "batch_id","timestamp","source","category","title",
        "price_usd","shipping_usd","total_usd","asin_sku",
        "tipo_cambio","costo_total_pen","precio_techo_pen",
        "precio_venta_pen","margen_neto_pen","roi_pct","accion",
        "url","rating","reviews",
    ]

    new_rows = []
    if import_path.exists():
        with open(import_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cat = row.get("category","")
                precio_techo = precios_techo.get(cat, 0)
                try:
                    roi = calcular_roi(
                        price_usd       = float(row.get("price_usd", 0)),
                        shipping_usd    = float(row.get("shipping_usd", 0)),
                        tipo_cambio     = tipo_cambio,
                        precio_techo_pen= precio_techo,
                    )
                except:
                    roi = {"costo_total_pen":0,"precio_venta_pen":0,
                           "margen_neto_pen":0,"roi_pct":0,"accion":"ERROR"}

                new_rows.append({
                    "batch_id":         row.get("batch_id",""),
                    "timestamp":        row.get("timestamp",""),
                    "source":           row.get("source",""),
                    "category":         cat,
                    "title":            row.get("title",""),
                    "price_usd":        row.get("price_usd",""),
                    "shipping_usd":     row.get("shipping_usd",""),
                    "total_usd":        row.get("total_usd",""),
                    "asin_sku":         row.get("asin_sku",""),
                    "tipo_cambio":      tipo_cambio,
                    "costo_total_pen":  roi.get("costo_total_pen",""),
                    "precio_techo_pen": precio_techo,
                    "precio_venta_pen": roi.get("precio_venta_pen",""),
                    "margen_neto_pen":  roi.get("margen_neto_pen",""),
                    "roi_pct":          roi.get("roi_pct",""),
                    "accion":           roi.get("accion",""),
                    "url":              row.get("url",""),
                    "rating":           row.get("rating",""),
                    "reviews":          row.get("reviews",""),
                })

    # Escribir en master.csv (append)
    write_header = not master_path.exists()
    with open(master_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=master_fields, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerows(new_rows)

    log.info(f"Master actualizado: +{len(new_rows)} filas → {master_path}")
    return len(new_rows)

# ── Reporte JSON ──────────────────────────────────────────────────────────────
def generar_reporte(batch_id: str, stats: dict, tipo_cambio: float):
    reporte = {
        "batch_id":    batch_id,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "tipo_cambio": tipo_cambio,
        "stats":       stats,
    }
    path = OUTPUT_DIR / f"reporte_{batch_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False)
    log.info(f"Reporte → {path}")
    return reporte

# ── Obtener tipo de cambio ────────────────────────────────────────────────────
def get_tipo_cambio() -> float:
    """Obtiene tipo de cambio USD/PEN en tiempo real."""
    try:
        resp = __import__("requests").get(
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=10
        )
        data = resp.json()
        tc = float(data["rates"]["PEN"])
        log.info(f"Tipo de cambio USD/PEN: {tc}")
        return tc
    except:
        log.warning("No se pudo obtener tipo de cambio — usando 3.75")
        return 3.75

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Pipeline scraping hardware PE")
    parser.add_argument("--only",       choices=["importacion","competencia","ambos"], default="ambos")
    parser.add_argument("--categories", nargs="+", default=None,
                        help="Categorías a scrapear: CPU GPU RAM SSD MOTHERBOARD PSU COOLER CASE")
    parser.add_argument("--max-pages",  type=int, default=None)
    parser.add_argument("--tc",         type=float, default=None, help="Tipo de cambio manual USD/PEN")
    args = parser.parse_args()

    batch_id     = datetime.now().strftime("%Y%m%d_%H%M%S")
    tipo_cambio  = args.tc or get_tipo_cambio()
    stats        = {}

    if args.max_pages:
        os.environ["MAX_PAGES_IMPORT"] = str(args.max_pages)
        os.environ["MAX_PAGES_COMP"]   = str(args.max_pages)

    log.info(f"{'='*60}")
    log.info(f"BATCH: {batch_id}")
    log.info(f"TC USD/PEN: {tipo_cambio}")
    log.info(f"Modo: {args.only}")
    log.info(f"{'='*60}")

    # ── Scraping importación ──────────────────────────────────────────────────
    if args.only in ("importacion", "ambos"):
        log.info("\n🌎 SCRAPING IMPORTACIÓN (Amazon / AliExpress / eBay)")
        _, total_import, stats_import = run_importacion(
            batch_id   = batch_id,
            categories = args.categories,
        )
        stats["importacion"] = {"total": total_import, **stats_import}

    # ── Scraping competencia ──────────────────────────────────────────────────
    if args.only in ("competencia", "ambos"):
        log.info("\n🏪 SCRAPING COMPETENCIA (Falabella / Ripley / Hiraoka)")
        _, total_comp, stats_comp = run_competencia(
            batch_id   = batch_id,
            categories = args.categories,
        )
        stats["competencia"] = {"total": total_comp, **stats_comp}

    # ── Consolidar master + ROI ───────────────────────────────────────────────
    if args.only == "ambos":
        log.info("\n📊 CONSOLIDANDO MASTER CSV + ROI")
        total_master = consolidar_master(batch_id, tipo_cambio)
        stats["master_nuevos"] = total_master

    # ── Reporte ───────────────────────────────────────────────────────────────
    reporte = generar_reporte(batch_id, stats, tipo_cambio)

    log.info(f"\n{'='*60}")
    log.info("RESUMEN FINAL")
    log.info(f"{'='*60}")
    for k, v in stats.items():
        log.info(f"  {k}: {v}")
    log.info(f"{'='*60}\n")

    # Output para GitHub Actions
    print(f"BATCH_ID={batch_id}")
    print(f"TOTAL_IMPORT={stats.get('importacion',{}).get('total',0)}")
    print(f"TOTAL_COMP={stats.get('competencia',{}).get('total',0)}")
    print(f"TIPO_CAMBIO={tipo_cambio}")

if __name__ == "__main__":
    main()
