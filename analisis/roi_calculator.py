"""
roi_calculator.py  v2.0
══════════════════════════
Calcula el ROI real de importar un producto desde USA a Perú.

Fórmula de costo total de importación (Perú - SUNAT):
┌─────────────────────────────────────────────────────────┐
│ FOB_efectivo = Precio_origen + Envío_doméstico_USA      │
│ CIF = FOB_efectivo + Flete_internacional + Seguro       │
│ Ad Valorem = CIF × 0%  (electrónica — SUNAT 2024)      │
│ IGV = (CIF + Ad Valorem) × 18%                         │
│ IPM = (CIF + Ad Valorem) × 2%                          │
│ Costo_Total_USD = CIF + Ad Valorem + IGV + IPM          │
│ Costo_Total_PEN = Costo_Total_USD × TC_venta            │
│                                                         │
│ ROI = (Precio_Local_PEN - Costo_Total_PEN)              │
│       ─────────────────────────────────── × 100         │
│              Costo_Total_PEN                            │
└─────────────────────────────────────────────────────────┘

Fixes v2.0:
  - [FIX-1] logging.basicConfig() eliminado del top-level
  - [FIX-2] Import scraper_dolar corregido (ruta desde agent/)
  - [FIX-3] get_usd_pen() llamado UNA SOLA VEZ — no en __post_init__
  - [FIX-4] source_type derivado desde columna 'source' de los scrapers
  - [FIX-5] Normalización de categorías (español ↔ inglés)
  - [FIX-6] score sin cap — permite ranking entre ROI > 100%
  - [FIX-7] conviene_importar sin == True (pandas warning)
  - [FIX-8] shipping_origen_usd documentado como parte del FOB efectivo
"""
"""
... (docstring existente sin cambios)
"""

# ── Path fix ─────────────────────────────────────────────────────────────
# Permite encontrar config.py (en configuracion/) y scrapers/ (en agent/)
# independientemente de desde dónde se ejecute el script.
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent   # sube de analisis/ → raíz del repo
sys.path.insert(0, str(_ROOT / "configuracion")) # → encuentra config.py ✅
sys.path.insert(0, str(_ROOT / "agent"))         # → encuentra scrapers/ ✅
# ─────────────────────────────────────────────────────────────────────────

import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

import pandas as pd

from config import (
    ARANCEL_AD_VALOREM, IGV, IPM,
    FLETE_BASE_USD, FLETE_POR_KG_USD, SEGURO_PCT,
    GASTO_DESPACHO_USD, MARGEN_GANANCIA_MIN,
    LIMITE_COURIER_USD, OPORTUNIDADES_CSV,
)
# FIX-2: import correcto desde agent/
from scrapers import get_exchange_rate

# FIX-1: Sin basicConfig() — logging configurado solo en main.py / pipeline
log = logging.getLogger(__name__)


# ── Clasificación de fuentes ──────────────────────────────────────────────
# FIX-4: Derivar source_type desde la columna 'source' generada por los scrapers
LOCAL_SOURCES = {
    "falabella_pe", "ripley_pe", "hiraoka_pe",
    "falabella", "ripley", "hiraoka",
    "competencia",
}
IMPORT_SOURCES = {
    "amazon_usa", "aliexpress", "ebay_usa", "ebay",
    "ebay_browse", "camelcamelcamel",
}

# FIX-5: Mapeo de categorías español → inglés (scrapers locales → scrapers importación)
CATEGORY_MAP = {
    # Español (scrapers locales PE)
    "laptops":              "LAPTOP",
    "computadoras":         "CPU",
    "procesadores":         "CPU",
    "tarjetas_video":       "GPU",
    "monitores":            "MONITOR",
    "memorias_ram":         "RAM",
    "discos_duros":         "SSD",
    "teclados":             "KEYBOARD",
    "mouse":                "MOUSE",
    "tablets":              "TABLET",
    "celulares":            "PHONE",
    "televisores":          "TV",
    "auriculares":          "AUDIO",
    "camaras":              "CAMERA",
    "videojuegos":          "GAMING",
    "impresoras":           "PRINTER",
    # Inglés (scrapers importación)
    "cpu":                  "CPU",
    "gpu":                  "GPU",
    "ram":                  "RAM",
    "ssd":                  "SSD",
    "motherboard":          "MOTHERBOARD",
    "psu":                  "PSU",
    "cooler":               "COOLER",
    "case":                 "CASE",
    "laptop":               "LAPTOP",
    "monitor":              "MONITOR",
    "video-card":           "GPU",
    "memory":               "RAM",
    "internal-hard-drive":  "SSD",
    "power-supply":         "PSU",
    "cpu-cooler":           "COOLER",
}

def _normalize_category(cat: str) -> str:
    """Normaliza categoría a vocabulario común (mayúsculas)."""
    if not cat:
        return "OTHER"
    return CATEGORY_MAP.get(str(cat).lower().strip(), str(cat).upper().strip())


# ── Pesos estimados por categoría (kg) ────────────────────────────────────
CATEGORY_WEIGHTS = {
    "CPU":         0.3,
    "GPU":         1.2,
    "RAM":         0.1,
    "SSD":         0.1,
    "MOTHERBOARD": 1.5,
    "PSU":         2.5,
    "COOLER":      1.0,
    "CASE":        8.0,
    "LAPTOP":      2.0,
    "MONITOR":     4.0,
    # ── Agregados ──────────────────────
    "TABLET":      0.6,
    "PHONE":       0.3,
    "TV":         12.0,   # ← sin esto, flete TV se calcula como 0.5 kg → ROI inflado
    "AUDIO":       0.4,
    "CAMERA":      0.5,
    "GAMING":      0.4,
    "PRINTER":     5.0,
    "KEYBOARD":    0.8,
    "MOUSE":       0.2,
}


# ══════════════════════════════════════════════════════════════════════════
# DATACLASSES
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class ImportCost:
    """
    Desglose completo del costo de importación.
    FIX-3: usd_pen se pasa como parámetro — no se hace HTTP en __post_init__.
    FIX-8: shipping_origen_usd es parte del FOB efectivo (envío doméstico USA).
    """
    # Inputs
    price_fob_usd:           float = 0.0   # Precio en origen (Amazon/eBay/Ali)
    shipping_origen_usd:     float = 0.0   # Envío doméstico USA — parte del FOB efectivo
    flete_internacional_usd: float = 0.0   # Courier USA → Perú
    peso_kg:                 float = 0.5   # Peso estimado del producto
    usd_pen_rate:            float = 0.0   # FIX-3: tipo de cambio pre-obtenido

    # Calculados
    seguro_usd:              float = field(default=0.0, init=False)
    cif_usd:                 float = field(default=0.0, init=False)
    ad_valorem_usd:          float = field(default=0.0, init=False)
    igv_usd:                 float = field(default=0.0, init=False)
    ipm_usd:                 float = field(default=0.0, init=False)
    gasto_despacho_usd:      float = field(default=0.0, init=False)
    total_impuestos_usd:     float = field(default=0.0, init=False)
    costo_total_usd:         float = field(default=0.0, init=False)
    costo_total_pen:         float = field(default=0.0, init=False)
    regimen:                 str   = field(default="", init=False)

    def __post_init__(self):
        # FIX-3: Si no se pasó el tipo de cambio, obtenerlo UNA vez
        # (en analyze_dataframe se pasa pre-obtenido para evitar 10k llamadas)
        if self.usd_pen_rate <= 0:
            rate = get_exchange_rate()
            self.usd_pen_rate = rate.get("usd_pen_venta", 3.75)
        self._calculate()

    def _calculate(self):
        # Flete internacional (si no se especificó, calcular por peso)
        if self.flete_internacional_usd == 0:
            self.flete_internacional_usd = round(
                FLETE_BASE_USD + max(0, self.peso_kg - 0.5) * FLETE_POR_KG_USD, 2
            )

        # Seguro = SEGURO_PCT del FOB (0.5% por defecto)
        fob_efectivo    = self.price_fob_usd + self.shipping_origen_usd
        self.seguro_usd = round(fob_efectivo * SEGURO_PCT, 2)

        # CIF = FOB_efectivo + Flete_internacional + Seguro
        self.cif_usd = round(
            fob_efectivo +
            self.flete_internacional_usd +
            self.seguro_usd, 2
        )

        # Régimen aduanero
        if self.cif_usd <= LIMITE_COURIER_USD:
            self.regimen             = "courier_simplificado"
            self.ad_valorem_usd      = 0.0
            self.igv_usd             = 0.0
            self.ipm_usd             = 0.0
            self.gasto_despacho_usd  = 0.0
            self.total_impuestos_usd = 0.0
        else:
            self.regimen          = "importacion_general"
            self.ad_valorem_usd   = round(self.cif_usd * ARANCEL_AD_VALOREM, 2)
            base_igv              = self.cif_usd + self.ad_valorem_usd
            self.igv_usd          = round(base_igv * IGV, 2)
            self.ipm_usd          = round(base_igv * IPM, 2)
            self.gasto_despacho_usd = GASTO_DESPACHO_USD
            self.total_impuestos_usd = round(
                self.ad_valorem_usd + self.igv_usd +
                self.ipm_usd + self.gasto_despacho_usd, 2
            )

        self.costo_total_usd = round(self.cif_usd + self.total_impuestos_usd, 2)
        self.costo_total_pen = round(self.costo_total_usd * self.usd_pen_rate, 2)


@dataclass
class ROIResult:
    """Resultado del análisis ROI para un producto."""
    title:             str   = ""
    category:          str   = ""
    source_import:     str   = ""
    source_local:      str   = ""
    price_import_usd:  float = 0.0
    price_local_pen:   float = 0.0
    costo_total_pen:   float = 0.0
    usd_pen:           float = 0.0
    ahorro_pen:        float = 0.0
    roi_pct:           float = 0.0
    margen_pct:        float = 0.0
    flete_usd:         float = 0.0
    impuestos_usd:     float = 0.0
    regimen:           str   = ""
    conviene_importar: bool  = False
    razon:             str   = ""
    score:             float = 0.0   # FIX-6: sin cap — permite ranking entre ROI > 100%
    url_import:        str   = ""
    url_local:         str   = ""


# ══════════════════════════════════════════════════════════════════════════
# CALCULADORA
# ══════════════════════════════════════════════════════════════════════════

def calculate_roi(
    price_import_usd:    float,
    price_local_pen:     float,
    shipping_origen_usd: float = 0.0,
    peso_kg:             float = 0.5,
    title:               str   = "",
    category:            str   = "",
    source_import:       str   = "",
    source_local:        str   = "",
    url_import:          str   = "",
    url_local:           str   = "",
    usd_pen_rate:        float = 0.0,   # FIX-3: pasar pre-obtenido para batch
) -> ROIResult:
    """
    Calcula el ROI de importar un producto específico.
    usd_pen_rate: si se pasa > 0, evita la llamada HTTP al tipo de cambio.
    """
    cost = ImportCost(
        price_fob_usd=price_import_usd,
        shipping_origen_usd=shipping_origen_usd,
        peso_kg=peso_kg,
        usd_pen_rate=usd_pen_rate,   # FIX-3
    )

    ahorro   = price_local_pen - cost.costo_total_pen
    roi      = (ahorro / cost.costo_total_pen * 100) if cost.costo_total_pen > 0 else 0.0
    margen   = (ahorro / price_local_pen * 100) if price_local_pen > 0 else 0.0
    conviene = roi >= (MARGEN_GANANCIA_MIN * 100)

    if price_local_pen <= 0:
        razon = "Sin precio local de referencia"
    elif price_import_usd <= 0:
        razon = "Sin precio de importación"
    elif conviene:
        razon = f"Ahorro S/ {ahorro:.2f} ({roi:.1f}% ROI) — {cost.regimen}"
    else:
        if ahorro > 0:
            razon = f"Ahorro insuficiente: S/ {ahorro:.2f} ({roi:.1f}% < {MARGEN_GANANCIA_MIN*100:.0f}% mínimo)"
        else:
            razon = f"No conviene: importar cuesta S/ {-ahorro:.2f} MÁS que comprar local"

    # FIX-6: score = roi sin cap — permite diferenciar ROI 150% vs 200%
    score = round(roi, 2) if conviene else 0.0

    return ROIResult(
        title=title,
        category=_normalize_category(category),
        source_import=source_import,
        source_local=source_local,
        price_import_usd=price_import_usd,
        price_local_pen=price_local_pen,
        costo_total_pen=cost.costo_total_pen,
        usd_pen=cost.usd_pen_rate,
        ahorro_pen=round(ahorro, 2),
        roi_pct=round(roi, 2),
        margen_pct=round(margen, 2),
        flete_usd=cost.flete_internacional_usd,
        impuestos_usd=cost.total_impuestos_usd,
        regimen=cost.regimen,
        conviene_importar=conviene,
        razon=razon,
        score=score,
        url_import=url_import,
        url_local=url_local,
    )


# ══════════════════════════════════════════════════════════════════════════
# ANÁLISIS MASIVO SOBRE DATAFRAME
# ══════════════════════════════════════════════════════════════════════════

def analyze_dataframe(df_master: pd.DataFrame, save: bool = True) -> pd.DataFrame:
    """
    Analiza el MASTER CSV y calcula ROI para cada par
    (producto_importación, precio_local_referencia).

    FIX-3: Obtiene usd_pen UNA SOLA VEZ antes del loop.
    FIX-4: Deriva source_type desde columna 'source'.
    FIX-5: Normaliza categorías antes del merge.
    """
    if df_master.empty:
        log.warning("DataFrame vacío")
        return pd.DataFrame()

    # FIX-3: Obtener tipo de cambio UNA SOLA VEZ
    rate_data = get_exchange_rate()
    usd_pen   = rate_data.get("usd_pen_venta", 3.75)
    log.info(f"  Tipo de cambio: S/ {usd_pen:.4f} por USD")

    # FIX-4: Derivar source_type desde columna 'source'
    df = df_master.copy()
    df["source_type"] = df["source"].apply(
        lambda s: "local_pe"    if str(s).lower() in LOCAL_SOURCES
                  else "importacion" if str(s).lower() in IMPORT_SOURCES
                  else "other"
    )

    # FIX-5: Normalizar categorías
    df["category_norm"] = df["category"].apply(_normalize_category)

    results = []

    for category in df["category_norm"].unique():
        if category == "OTHER":
            continue

        cat_df    = df[df["category_norm"] == category]
        local_df  = cat_df[cat_df["source_type"] == "local_pe"]
        import_df = cat_df[cat_df["source_type"] == "importacion"]

        if local_df.empty or import_df.empty:
            log.debug(f"  {category}: sin datos locales o de importación")
            continue

        local_df["price_pen"] = pd.to_numeric(local_df["price_pen"], errors="coerce")
        local_df = local_df[local_df["price_pen"].notna() & (local_df["price_pen"] > 0)]
        if local_df.empty:
            continue

        precio_mediano_pen = local_df["price_pen"].median()
        precio_min_pen     = local_df["price_pen"].min()
        precio_max_pen     = local_df["price_pen"].max()
        peso_kg            = CATEGORY_WEIGHTS.get(category, 0.5)

        log.info(f"  {category}: {len(import_df)} productos importación | "
                 f"Precio local mediano: S/ {precio_mediano_pen:.2f}")

        for _, row in import_df.iterrows():
            try:
                price_usd = float(row.get("price_usd") or 0)
                ship_usd  = float(row.get("shipping_usd") or 0)
                if price_usd <= 0:
                    continue

                roi_result = calculate_roi(
                    price_import_usd=price_usd,
                    price_local_pen=precio_mediano_pen,
                    shipping_origen_usd=ship_usd,
                    peso_kg=peso_kg,
                    title=str(row.get("title", "")),
                    category=category,
                    source_import=str(row.get("source", "")),
                    source_local="mercado_local_pe",
                    url_import=str(row.get("url", "")),
                    usd_pen_rate=usd_pen,   # FIX-3: reutilizar el mismo rate
                )

                result_dict = asdict(roi_result)
                result_dict["precio_local_min_pen"]    = precio_min_pen
                result_dict["precio_local_max_pen"]    = precio_max_pen
                result_dict["precio_local_median_pen"] = precio_mediano_pen
                result_dict["batch_id"]                = str(row.get("batch_id", ""))
                results.append(result_dict)

            except Exception as e:
                log.debug(f"    Error procesando fila: {e}")
                continue

    if not results:
        log.warning("No se generaron resultados ROI")
        return pd.DataFrame()

    df_roi = pd.DataFrame(results).sort_values("roi_pct", ascending=False)

    # FIX-7: sin == True (pandas warning)
    conviene = df_roi[df_roi["conviene_importar"]]

    log.info(f"\n{'='*60}")
    log.info(f"ANÁLISIS ROI COMPLETO")
    log.info(f"  Total evaluados   : {len(df_roi):,}")
    log.info(f"  Conviene importar : {len(conviene):,} ({len(conviene)/len(df_roi)*100:.1f}%)")
    if not conviene.empty:
        log.info(f"  Mejor ROI         : {conviene['roi_pct'].max():.1f}%")
        log.info(f"  Mejor ahorro      : S/ {conviene['ahorro_pen'].max():.2f}")
    log.info(f"{'='*60}")

    if save:
        df_roi.to_csv(OPORTUNIDADES_CSV, index=False, encoding="utf-8")
        log.info(f"  💾 Oportunidades guardadas en {OPORTUNIDADES_CSV}")

    return df_roi


def top_oportunidades(n: int = 20, category: str = None) -> pd.DataFrame:
    """Retorna el top N de oportunidades de importación."""
    if not OPORTUNIDADES_CSV.exists():
        log.warning("No existe oportunidades_roi.csv. Ejecutar analyze_dataframe() primero.")
        return pd.DataFrame()

    df = pd.read_csv(OPORTUNIDADES_CSV)
    # FIX-7: sin == True
    df = df[df["conviene_importar"]]

    if category:
        df = df[df["category"].str.upper() == category.upper()]

    return df.nlargest(n, "roi_pct")[[
        "category", "title", "price_import_usd", "costo_total_pen",
        "price_local_pen", "ahorro_pen", "roi_pct", "regimen",
        "source_import", "url_import",
    ]]


# ══════════════════════════════════════════════════════════════════════════
# STANDALONE — TEST
# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    print("\n" + "=" * 60)
    print("TEST ROI CALCULATOR v2.0")
    print("=" * 60)

    test_cases = [
        {"title": "Intel Core i7-13700K",    "price_usd": 280.0, "price_pen": 1450.0, "category": "CPU"},
        {"title": "NVIDIA RTX 4070",          "price_usd": 550.0, "price_pen": 2800.0, "category": "GPU"},
        {"title": "Samsung 990 Pro 1TB NVMe", "price_usd":  89.0, "price_pen":  420.0, "category": "SSD"},
        {"title": "Corsair RM850x PSU",       "price_usd": 120.0, "price_pen":  550.0, "category": "PSU"},
    ]

    for tc in test_cases:
        r = calculate_roi(
            price_import_usd=tc["price_usd"],
            price_local_pen=tc["price_pen"],
            peso_kg=CATEGORY_WEIGHTS.get(tc["category"], 0.5),
            title=tc["title"],
            category=tc["category"],
        )
        icon = "✅" if r.conviene_importar else "❌"
        print(f"\n{icon} {r.title}")
        print(f"   Import: ${r.price_import_usd} USD → Costo total: S/ {r.costo_total_pen}")
        print(f"   Local : S/ {r.price_local_pen}")
        print(f"   Ahorro: S/ {r.ahorro_pen} | ROI: {r.roi_pct:.1f}% | Score: {r.score}")
        print(f"   Régimen: {r.regimen} | {r.razon}")
