#!/usr/bin/env python3
"""
roi_calculator.py  v3.0
══════════════════════════
Calcula el ROI real de importar un producto desde USA a Perú.

Fórmula de costo total de importación (Perú - SUNAT):
┌─────────────────────────────────────────────────────────┐
│ FOB_efectivo = Precio_origen + Envío_doméstico_USA      │
│ CIF = FOB_efectivo + Flete_internacional + Seguro       │
│                                                         │
│ Régimen de_minimis  (CIF ≤ $200):                       │
│   Sin impuestos                                         │
│                                                         │
│ Régimen courier_simplificado ($200 < CIF ≤ $2000):      │
│   Ad Valorem = 0%                                       │
│   IGV = CIF × 18%                                       │
│   IPM = CIF × 2%                                        │
│                                                         │
│ Régimen importacion_general (CIF > $2000):              │
│   Ad Valorem = CIF × 0%  (electrónica — SUNAT 2024)    │
│   IGV = (CIF + Ad Valorem) × 18%                       │
│   IPM = (CIF + Ad Valorem) × 2%                        │
│   Gasto despacho = fijo                                 │
│                                                         │
│ Costo_Total_USD = CIF + Impuestos                       │
│ Costo_Total_PEN = Costo_Total_USD × TC_venta            │
│                                                         │
│ ROI = (Precio_Local_PEN - Costo_Total_PEN)              │
│       ─────────────────────────────────── × 100         │
│              Costo_Total_PEN                            │
└─────────────────────────────────────────────────────────┘

Fixes v3.0 (sobre v2.0):
  - [R1] Doble docstring eliminado (string literal flotante inútil)
  - [R2] Tres regímenes SUNAT: de_minimis / courier_simplificado /
         importacion_general — v2.0 exoneraba IGV+IPM en rango $200-$2000
  - [R3] analyze_dataframe: .copy() en local_df e import_df —
         SettingWithCopyWarning / CoW silencioso en pandas 2.0+
         → precio_mediano_pen = NaN → todos los ROI = NaN
  - [R4] LOCAL_SOURCES: agregado 'mercadolibre_pe' —
         v2.0 ignoraba el 60%+ de los precios locales del MASTER
         IMPORT_SOURCES: agregado 'newegg_usa', 'pcpartpicker_current',
         'pcpartpicker_history'
  - [R5] top_oportunidades: validación de columnas antes de operar
  - [R6] CATEGORY_MAP: categorías Newegg v2.0 mapeadas
         ('cpu_intel','gpu_nvidia','ram_ddr4','ssd_nvme', etc.)
         → v2.0 calculaba flete con peso=0.5 kg para todos
"""

# ── Path fix ──────────────────────────────────────────────────────────────
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "configuracion"))
sys.path.insert(0, str(_ROOT / "agent"))
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
from scrapers import get_exchange_rate

log = logging.getLogger(__name__)

# [R2] Umbrales SUNAT diferenciados
_DE_MINIMIS_USD        = 200    # CIF ≤ $200: sin impuestos
_LIMITE_SIMPLIFICADO_USD = 2000 # $200 < CIF ≤ $2000: Ad Valorem 0%, IGV+IPM sí


# ── Clasificación de fuentes ──────────────────────────────────────────────
# [R4] LOCAL_SOURCES: agregado 'mercadolibre_pe'
LOCAL_SOURCES = {
    "falabella_pe", "ripley_pe", "hiraoka_pe",
    "falabella", "ripley", "hiraoka",
    "competencia",
    "mercadolibre_pe",          # [R4] scraper_mercadolibre v2.0
}
# [R4] IMPORT_SOURCES: agregado newegg_usa, pcpartpicker_*
IMPORT_SOURCES = {
    "amazon_usa", "aliexpress", "ebay_usa", "ebay",
    "ebay_browse", "camelcamelcamel",
    "newegg_usa",               # [R4] scraper_newegg v2.0
    "pcpartpicker_current",     # [R4] scraper_pcpartpicker v3.0
    "pcpartpicker_history",     # [R4] scraper_pcpartpicker v3.0
}

# [R6] CATEGORY_MAP: categorías Newegg v2.0 + categorías existentes
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
    # Inglés genérico (PCPartPicker, importación)
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
    # [R6] Newegg v2.0 — categorías compuestas
    "cpu_intel":            "CPU",
    "cpu_amd":              "CPU",
    "gpu_nvidia":           "GPU",
    "gpu_amd":              "GPU",
    "ram_ddr4":             "RAM",
    "ram_ddr5":             "RAM",
    "ssd_nvme":             "SSD",
    "ssd_sata":             "SSD",
    "hdd_interno":          "SSD",
    "mobo_intel":           "MOTHERBOARD",
    "mobo_amd":             "MOTHERBOARD",
    "cooler_aire":          "COOLER",
    "cooler_liquido":       "COOLER",
    "cases":                "CASE",
    "tarjetas_red":         "OTHER",
}

def _normalize_category(cat: str) -> str:
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
    "TABLET":      0.6,
    "PHONE":       0.3,
    "TV":         12.0,
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
    flete_internacional_usd=0.0 → calcular automáticamente por peso.
    """
    price_fob_usd:           float = 0.0
    shipping_origen_usd:     float = 0.0
    flete_internacional_usd: float = 0.0
    peso_kg:                 float = 0.5
    usd_pen_rate:            float = 0.0

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
        if self.usd_pen_rate <= 0:
            rate = get_exchange_rate()
            self.usd_pen_rate = rate.get("usd_pen_venta", 3.75)
        self._calculate()

    def _calculate(self):
        if self.flete_internacional_usd == 0:
            self.flete_internacional_usd = round(
                FLETE_BASE_USD + max(0, self.peso_kg - 0.5) * FLETE_POR_KG_USD, 2
            )

        fob_efectivo    = self.price_fob_usd + self.shipping_origen_usd
        self.seguro_usd = round(fob_efectivo * SEGURO_PCT, 2)
        self.cif_usd    = round(
            fob_efectivo + self.flete_internacional_usd + self.seguro_usd, 2
        )

        # [R2] Tres regímenes SUNAT diferenciados
        if self.cif_usd <= _DE_MINIMIS_USD:
            # De minimis: sin impuestos
            self.regimen             = "de_minimis"
            self.ad_valorem_usd      = 0.0
            self.igv_usd             = 0.0
            self.ipm_usd             = 0.0
            self.gasto_despacho_usd  = 0.0
            self.total_impuestos_usd = 0.0

        elif self.cif_usd <= _LIMITE_SIMPLIFICADO_USD:
            # Courier simplificado: Ad Valorem 0%, IGV 18%, IPM 2%
            self.regimen          = "courier_simplificado"
            self.ad_valorem_usd   = 0.0
            self.igv_usd          = round(self.cif_usd * IGV, 2)
            self.ipm_usd          = round(self.cif_usd * IPM, 2)
            self.gasto_despacho_usd = 0.0
            self.total_impuestos_usd = round(
                self.igv_usd + self.ipm_usd, 2
            )

        else:
            # Importación general: Ad Valorem + IGV + IPM + despacho
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
    score:             float = 0.0
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
    usd_pen_rate:        float = 0.0,
) -> ROIResult:
    cost = ImportCost(
        price_fob_usd=price_import_usd,
        shipping_origen_usd=shipping_origen_usd,
        peso_kg=peso_kg,
        usd_pen_rate=usd_pen_rate,
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
    """
    if df_master.empty:
        log.warning("DataFrame vacío")
        return pd.DataFrame()

    rate_data = get_exchange_rate()
    usd_pen   = rate_data.get("usd_pen_venta", 3.75)
    log.info(f"  Tipo de cambio: S/ {usd_pen:.4f} por USD")

    df = df_master.copy()
    df["source_type"] = df["source"].apply(
        lambda s: "local_pe"    if str(s).lower() in LOCAL_SOURCES
                  else "importacion" if str(s).lower() in IMPORT_SOURCES
                  else "other"
    )
    df["category_norm"] = df["category"].apply(_normalize_category)

    results = []

    for category in df["category_norm"].unique():
        if category == "OTHER":
            continue

        cat_df = df[df["category_norm"] == category]

        # [R3] .copy() — evita SettingWithCopyWarning y CoW silencioso en pandas 2.0+
        local_df  = cat_df[cat_df["source_type"] == "local_pe"].copy()
        import_df = cat_df[cat_df["source_type"] == "importacion"].copy()

        if local_df.empty or import_df.empty:
            log.debug(f"  {category}: sin datos locales o de importación")
            continue

        # [R3] Ahora sí modifica local_df (es una copia, no una vista)
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
                    usd_pen_rate=usd_pen,
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

    df_roi   = pd.DataFrame(results).sort_values("roi_pct", ascending=False)
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

    # [R5] Validar columnas antes de operar — evita KeyError con CSV de versión anterior
    _required = {"roi_pct", "conviene_importar", "category", "title",
                 "price_import_usd", "costo_total_pen", "price_local_pen",
                 "ahorro_pen", "regimen", "source_import", "url_import"}
    _missing  = _required - set(df.columns)
    if _missing:
        log.warning(f"  [top_oportunidades] CSV desactualizado — columnas faltantes: {_missing}")
        return pd.DataFrame()

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
    print("TEST ROI CALCULATOR v3.0")
    print("=" * 60)

    test_cases = [
        {"title": "Intel Core i7-13700K",    "price_usd": 280.0, "price_pen": 1450.0, "category": "CPU"},
        {"title": "NVIDIA RTX 4070",          "price_usd": 550.0, "price_pen": 2800.0, "category": "GPU"},
        {"title": "Samsung 990 Pro 1TB NVMe", "price_usd":  89.0, "price_pen":  420.0, "category": "SSD"},
        {"title": "Corsair RM850x PSU",       "price_usd": 120.0, "price_pen":  550.0, "category": "PSU"},
        # [R2] Test de_minimis
        {"title": "USB Hub 4 puertos",        "price_usd":  15.0, "price_pen":   85.0, "category": "OTHER"},
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
