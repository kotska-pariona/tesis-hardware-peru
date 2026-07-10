"""
main.py  v4.1
══════════════
Orquestador principal del pipeline de scraping.
Ejecuta scraper_importacion + scraper_competencia
y consolida todo en MASTER_hardware_peru.csv con ROI calculado.

Uso:
  python agent/main.py                        # ejecuta todo
  python agent/main.py --only importacion     # solo fuentes de importación
  python agent/main.py --only competencia     # solo fuentes de competencia
  python agent/main.py --categories CPU GPU   # solo esas categorías
"""

import os, sys, csv, json, logging, argparse
import requests                                      # ✅ FIX 4: import normal
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "data/raw"))  # ✅ FIX 1
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)            # ✅ FIX 3

# ── Importar scrapers ─────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
try:
    from scrapers.scraper_importacion import run_importacion
    from scrapers.scraper_competencia import run_competencia
except ImportError:
    from scraper_importacion import run_importacion
    from scraper_competencia import run_competencia

# ── ROI Calculator ────────────────────────────────────────────────────────────
def calcular_roi(
    price_usd: float,
    shipping_usd: float,
    tipo_cambio: float,
    precio_techo_pen: float,
    arancel_pct: float = 0.18,
    ad_valorem_pct: float = 0.0,
    courier_pen: float = 50.0,
    margen_minimo_pct: float = 0.20,
) -> dict:
    if price_usd <= 0 or tipo_cambio <= 0:
        return {
            "costo_fob_pen": 0, "tributos_pen": 0, "costo_total_pen": 0,
            "precio_venta_pen": 0, "margen_neto_pen": 0,
            "roi_pct": 0, "viable": False, "accion": "DATOS_INSUFICIENTES"
        }

    costo_fob_pen    = (price_usd + shipping_usd) * tipo_cambio
    tributos_pen     = costo_fob_pen * (arancel_pct + ad_valorem_pct)
    costo_total_pen  = costo_fob_pen + tributos_pen + courier_pen
    precio_venta_pen = precio_techo_pen * 0.90
    margen_neto_pen  = precio_venta_pen - costo_total_pen
    roi_pct          = (margen_neto_pen / costo_total_pen * 100) if costo_total_pen > 0 else 0

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

# ── Consolidar MASTER_hardware_peru.csv ───────────────────────────────────────
def consolidar_master(batch_id: str, tipo_cambio: float):
    master_path = OUTPUT_DIR / "MASTER_hardware_peru.csv"   # ✅ FIX 2
    import_path = OUTPUT_DIR / f"importacion_{batch_id}.csv"
    comp_path   = OUTPUT_DIR / f"competencia_{batch_id}.csv"

    # ── Leer precios techo por categoría ─────────────────────────────────────
    precios_techo = {}
    if comp_path.exists():
        with open(comp_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cat = row.get("category", "")
                try:
                    p = float(row.get("price_pen", 0))
                    if p > precios_techo.get(cat, 0):
                        precios_techo[cat] = p
                except:
                    pass
        log.info(f"Precios techo por categoría: {precios_techo}")
    else:
        log.warning(f"No se encontró archivo de competencia: {comp_path}")

    # ── Leer items de importación y calcular ROI ──────────────────────────────
    master_fields = [
        "batch_id", "timestamp", "source", "category", "title",
        "price_usd", "shipping_usd", "total_usd", "asin_sku",
        "tipo_cambio", "costo_total_pen", "precio_techo_pen",
        "precio_venta_pen", "margen_neto_pen", "roi_pct", "accion",
        "url", "rating", "reviews",
    ]

    new_rows = []
    if not import_path.exists():
        log.warning(f"No se encontró archivo de importación: {import_path}")
        return 0

    with open(import_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cat          = row.get("category", "")
            precio_techo = precios_techo.get(cat, 0)

            # ✅ FIX 5: fallback si no hay precio techo
            if precio_techo == 0:
                try:
                    precio_techo = float(row.get("total_usd", 0)) * tipo_cambio * 2.0
                    log.debug(f"Usando precio techo estimado para {cat}: S/{precio_techo:.2f}")
                except:
                    precio_techo = 0

            try:
                roi = calcular_roi(
                    price_usd        = float(row.get("price_usd", 0)),
                    shipping_usd     = float(row.get("shipping_usd", 0)),
                    tipo_cambio      = tipo_cambio,
                    precio_techo_pen = precio_techo,
                )
            except Exception as e:
                log.debug(f"Error calculando ROI: {e}")
                roi = {
                    "costo_total_pen": 0, "precio_venta_pen": 0,
                    "margen_neto_pen": 0, "roi_pct": 0, "accion": "ERROR"
                }

            new_rows.append({
                "batch_id":          row.get("batch_id", ""),
                "timestamp":         row.get("timestamp", ""),
                "source":            row.get("source", ""),
                "category":          cat,
                "title":             row.get("title", ""),
                "price_usd":         row.get("price_usd", ""),
                "shipping_usd":      row.get("shipping_usd", ""),
                "total_usd":         row.get("total_usd", ""),
                "asin_sku":          row.get("asin_sku", ""),
                "tipo_cambio":       tipo_cambio,
                "costo_total_pen":   roi.get("costo_total_pen", ""),
                "precio_techo_pen":  precio_techo,
                "precio_venta_pen":  roi.get("precio_venta_pen", ""),
                "margen_neto_pen":   roi.get("margen_neto_pen", ""),
                "roi_pct":           roi.get("roi_pct", ""),
                "accion":            roi.get("accion", ""),
                "url":               row.get("url", ""),
                "rating":            row.get("rating", ""),
                "reviews":           row.get("reviews", ""),
            })

    # ── Append a MASTER_hardware_peru.csv ─────────────────────────────────────
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

# ── Tipo de cambio USD/PEN ────────────────────────────────────────────────────
def get_tipo_cambio() -> float:
    try:
        resp = requests.get(                              # ✅ FIX 4: import normal
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=10
        )
        data = resp.json()
        tc = float(data["rates"]["PEN"])
        log.info(f"Tipo de cambio USD/PEN: {tc}")
        return tc
    except Exception as e:
        log.warning(f"No se pudo obtener tipo de cambio ({e}) — usando 3.75")
        return 3.75

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Pipeline scraping hardware PE v4.1")
    parser.add_argument("--only",       choices=["importacion", "competencia", "ambos"], default="ambos")
    parser.add_argument("--categories", nargs="+", default=None,
                        help="CPU GPU RAM SSD MOTHERBOARD PSU COOLER CASE")
    parser.add_argument("--max-pages",  type=int, default=None)
    parser.add_argument("--tc",         type=float, default=None,
                        help="Tipo de cambio manual USD/PEN (ej: 3.75)")
    args = parser.parse_args()

    batch_id    = datetime.now().strftime("%Y%m%d_%H%M%S")
    tipo_cambio = args.tc if args.tc else get_tipo_cambio()
    stats       = {}

    if args.max_pages:
        os.environ["MAX_PAGES_IMPORT"] = str(args.max_pages)
        os.environ["MAX_PAGES_COMP"]   = str(args.max_pages)

    log.info("=" * 60)
    log.info(f"BATCH    : {batch_id}")
    log.info(f"TC USD/PE: {tipo_cambio}")
    log.info(f"Modo     : {args.only}")
    log.info(f"OUTPUT   : {OUTPUT_DIR}")
    log.info("=" * 60)

    # ── Scraping importación ──────────────────────────────────────────────────
    if args.only in ("importacion", "ambos"):
        log.info("\n🌎 SCRAPING IMPORTACIÓN (Amazon / AliExpress / eBay)")
        try:
            _, total_import, stats_import = run_importacion(
                batch_id   = batch_id,
                categories = args.categories,
            )
            stats["importacion"] = {"total": total_import, **stats_import}
        except Exception as e:
            log.error(f"Error en scraping importación: {e}")
            stats["importacion"] = {"total": 0, "error": str(e)}

    # ── Scraping competencia ──────────────────────────────────────────────────
    if args.only in ("competencia", "ambos"):
        log.info("\n🏪 SCRAPING COMPETENCIA (Falabella / Ripley / Hiraoka)")
        try:
            _, total_comp, stats_comp = run_competencia(
                batch_id   = batch_id,
                categories = args.categories,
            )
            stats["competencia"] = {"total": total_comp, **stats_comp}
        except Exception as e:
            log.error(f"Error en scraping competencia: {e}")
            stats["competencia"] = {"total": 0, "error": str(e)}

    # ── Consolidar master + ROI ───────────────────────────────────────────────
    if args.only == "ambos":
        log.info("\n📊 CONSOLIDANDO MASTER CSV + ROI")
        try:
            total_master = consolidar_master(batch_id, tipo_cambio)
            stats["master_nuevos"] = total_master
        except Exception as e:
            log.error(f"Error consolidando master: {e}")
            stats["master_nuevos"] = 0

    # ── Reporte ───────────────────────────────────────────────────────────────
    generar_reporte(batch_id, stats, tipo_cambio)

    log.info("\n" + "=" * 60)
    log.info("RESUMEN FINAL")
    log.info("=" * 60)
    for k, v in stats.items():
        log.info(f"  {k}: {v}")
    log.info("=" * 60)

    # ── Outputs para GitHub Actions ───────────────────────────────────────────
    print(f"BATCH_ID={batch_id}")
    print(f"TOTAL_IMPORT={stats.get('importacion', {}).get('total', 0)}")
    print(f"TOTAL_COMP={stats.get('competencia', {}).get('total', 0)}")
    print(f"TIPO_CAMBIO={tipo_cambio}")

if __name__ == "__main__":
    main()
