"""
roi_calculator.py
══════════════════
Calcula el ROI real de importar un producto desde USA a Perú.

Fórmula de costo total de importación (Perú - SUNAT):
┌─────────────────────────────────────────────────────────┐
│ CIF = Precio_FOB + Flete + Seguro                       │
│ Ad Valorem = CIF × 0% (electrónica)                     │
│ IGV = (CIF + Ad Valorem) × 18%                          │
│ IPM = (CIF + Ad Valorem) × 2%                           │
│ Costo_Total_USD = CIF + Ad Valorem + IGV + IPM          │
│ Costo_Total_PEN = Costo_Total_USD × TC_venta            │
│                                                         │
│ ROI = (Precio_Local_PEN - Costo_Total_PEN)              │
│       ─────────────────────────────────── × 100         │
│              Costo_Total_PEN                            │
└─────────────────────────────────────────────────────────┘
"""

import logging
from dataclasses import dataclass, field, asdict
from typing import Optional
import pandas as pd

from config import (
    ARANCEL_AD_VALOREM, IGV, IPM,
    FLETE_BASE_USD, FLETE_POR_KG_USD, SEGURO_PCT,
    GASTO_DESPACHO_USD, MARGEN_GANANCIA_MIN,
    LIMITE_COURIER_USD, OPORTUNIDADES_CSV, LOG_LEVEL,
)
from scraper_dolar import get_usd_pen

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
log = logging.getLogger("roi_calculator")

# ══════════════════════════════════════════════════════════════════════════════
# DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ImportCost:
    """Desglose completo del costo de importación"""
    # Inputs
    price_fob_usd:      float = 0.0   # Precio en origen (Amazon/eBay/Ali)
    shipping_origen_usd: float = 0.0  # Envío dentro de USA (si aplica)
    flete_internacional_usd: float = 0.0  # Courier internacional
    peso_kg:            float = 0.5   # Peso estimado del producto

    # Calculados
    seguro_usd:         float = field(default=0.0, init=False)
    cif_usd:            float = field(default=0.0, init=False)
    ad_valorem_usd:     float = field(default=0.0, init=False)
    igv_usd:            float = field(default=0.0, init=False)
    ipm_usd:            float = field(default=0.0, init=False)
    gasto_despacho_usd: float = field(default=0.0, init=False)
    total_impuestos_usd: float = field(default=0.0, init=False)
    costo_total_usd:    float = field(default=0.0, init=False)

    # Con tipo de cambio
    usd_pen:            float = field(default=0.0, init=False)
    costo_total_pen:    float = field(default=0.0, init=False)

    # Régimen
    regimen:            str   = field(default="", init=False)

    def __post_init__(self):
        self._calculate()

    def _calculate(self):
        rate = get_usd_pen()
        self.usd_pen = rate["usd_pen_venta"]

        # Flete internacional (si no se especificó, calcular por peso)
        if self.flete_internacional_usd == 0:
            self.flete_internacional_usd = (
                FLETE_BASE_USD + max(0, self.peso_kg - 0.5) * FLETE_POR_KG_USD
            )

        # Seguro = 0.5% del FOB
        self.seguro_usd = round(self.price_fob_usd * SEGURO_PCT, 2)

        # CIF = FOB + Flete + Seguro
        self.cif_usd = round(
            self.price_fob_usd +
            self.shipping_origen_usd +
            self.flete_internacional_usd +
            self.seguro_usd, 2
        )

        # Determinar régimen aduanero
        if self.cif_usd <= LIMITE_COURIER_USD:
            # Régimen simplificado (courier < $200): exento de impuestos
            self.regimen          = "courier_simplificado"
            self.ad_valorem_usd   = 0.0
            self.igv_usd          = 0.0
            self.ipm_usd          = 0.0
            self.gasto_despacho_usd = 0.0
            self.total_impuestos_usd = 0.0
        else:
            # Régimen general: aplican impuestos
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
        self.costo_total_pen = round(self.costo_total_usd * self.usd_pen, 2)

@dataclass
class ROIResult:
    """Resultado del análisis ROI para un producto"""
    # Identificación
    title:              str   = ""
    category:           str   = ""
    source_import:      str   = ""
    source_local:       str   = ""

    # Precios
    price_import_usd:   float = 0.0
    price_local_pen:    float = 0.0
    costo_total_pen:    float = 0.0
    usd_pen:            float = 0.0

    # ROI
    ahorro_pen:         float = 0.0   # precio_local - costo_total
    roi_pct:            float = 0.0   # (ahorro / costo_total) * 100
    margen_pct:         float = 0.0   # (ahorro / precio_local) * 100

    # Desglose
    flete_usd:          float = 0.0
    impuestos_usd:      float = 0.0
    regimen:            str   = ""

    # Decisión
    conviene_importar:  bool  = False
    razon:              str   = ""
    score:              float = 0.0   # 0-100, para ranking

    # URLs
    url_import:         str   = ""
    url_local:          str   = ""

# ══════════════════════════════════════════════════════════════════════════════
# CALCULADORA
# ══════════════════════════════════════════════════════════════════════════════

def calculate_roi(
    price_import_usd:   float,
    price_local_pen:    float,
    shipping_origen_usd: float = 0.0,
    peso_kg:            float = 0.5,
    title:              str   = "",
    category:           str   = "",
    source_import:      str   = "",
    source_local:       str   = "",
    url_import:         str   = "",
    url_local:          str   = "",
) -> ROIResult:
    """
    Calcula el ROI de importar un producto específico.

    Args:
        price_import_usd:    Precio en USD (Amazon/eBay/AliExpress)
        price_local_pen:     Precio en PEN (Falabella/Ripley/Hiraoka)
        shipping_origen_usd: Costo de envío dentro de USA
        peso_kg:             Peso estimado del producto en kg

    Returns:
        ROIResult con análisis completo
    """
    cost = ImportCost(
        price_fob_usd=price_import_usd,
        shipping_origen_usd=shipping_origen_usd,
        peso_kg=peso_kg,
    )

    ahorro = price_local_pen - cost.costo_total_pen
    roi    = (ahorro / cost.costo_total_pen * 100) if cost.costo_total_pen > 0 else 0.0
    margen = (ahorro / price_local_pen * 100) if price_local_pen > 0 else 0.0

    # Determinar si conviene
    conviene = roi >= (MARGEN_GANANCIA_MIN * 100)

    # Razón
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

    # Score 0-100 para ranking
    score = min(100.0, max(0.0, roi)) if conviene else 0.0

    return ROIResult(
        title=title,
        category=category,
        source_import=source_import,
        source_local=source_local,
        price_import_usd=price_import_usd,
        price_local_pen=price_local_pen,
        costo_total_pen=cost.costo_total_pen,
        usd_pen=cost.usd_pen,
        ahorro_pen=round(ahorro, 2),
        roi_pct=round(roi, 2),
        margen_pct=round(margen, 2),
        flete_usd=cost.flete_internacional_usd,
        impuestos_usd=cost.total_impuestos_usd,
        regimen=cost.regimen,
        conviene_importar=conviene,
        razon=razon,
        score=round(score, 2),
        url_import=url_import,
        url_local=url_local,
    )

# ══════════════════════════════════════════════════════════════════════════════
# ANÁLISIS MASIVO SOBRE DATAFRAME
# ══════════════════════════════════════════════════════════════════════════════

# Pesos estimados por categoría (kg)
CATEGORY_WEIGHTS = {
    "CPU":         0.3,
    "GPU":         1.2,
    "RAM":         0.1,
    "SSD":         0.1,
    "MOTHERBOARD": 1.5,
    "PSU":         2.5,
    "COOLER":      1.0,
    "CASE":        8.0,
}

def analyze_dataframe(df_merged: pd.DataFrame, save: bool = True) -> pd.DataFrame:
    """
    Analiza un DataFrame mergeado y calcula ROI para cada par
    (producto_importación, precio_local_referencia).

    Estrategia de matching:
      - Agrupa por categoría
      - Usa el precio mediano local como referencia de mercado
      - Calcula ROI de cada producto de importación vs esa referencia
    """
    if df_merged.empty:
        log.warning("DataFrame vacío")
        return pd.DataFrame()

    results = []

    for category in df_merged["category"].unique():
        cat_df = df_merged[df_merged["category"] == category]

        # Precio de referencia local (mediana de precios en PEN)
        local_df = cat_df[cat_df["source_type"] == "local_pe"]
        import_df = cat_df[cat_df["source_type"] == "importacion"]

        if local_df.empty or import_df.empty:
            log.debug(f"  {category}: sin datos locales o de importación")
            continue

        local_df = local_df[local_df["price_pen"] > 0]
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
                price_usd = float(row.get("price_usd", 0) or 0)
                ship_usd  = float(row.get("shipping_usd", 0) or 0)
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

    df_roi = pd.DataFrame(results)
    df_roi = df_roi.sort_values("roi_pct", ascending=False)

    # Estadísticas
    conviene = df_roi[df_roi["conviene_importar"] == True]
    log.info(f"\n{'='*60}")
    log.info(f"ANÁLISIS ROI COMPLETO")
    log.info(f"  Total evaluados   : {len(df_roi)}")
    log.info(f"  Conviene importar : {len(conviene)} ({len(conviene)/len(df_roi)*100:.1f}%)")
    if not conviene.empty:
        log.info(f"  Mejor ROI         : {conviene['roi_pct'].max():.1f}%")
        log.info(f"  Mejor ahorro      : S/ {conviene['ahorro_pen'].max():.2f}")
    log.info(f"{'='*60}")

    if save:
        df_roi.to_csv(OPORTUNIDADES_CSV, index=False, encoding="utf-8")
        log.info(f"  💾 Oportunidades guardadas en {OPORTUNIDADES_CSV}")

    return df_roi

def top_oportunidades(n: int = 20, category: str = None) -> pd.DataFrame:
    """Retorna el top N de oportunidades de importación"""
    if not OPORTUNIDADES_CSV.exists():
        log.warning("No existe oportunidades_roi.csv. Ejecutar analyze_dataframe() primero.")
        return pd.DataFrame()

    df = pd.read_csv(OPORTUNIDADES_CSV)
    df = df[df["conviene_importar"] == True]

    if category:
        df = df[df["category"].str.upper() == category.upper()]

    return df.nlargest(n, "roi_pct")[[
        "category", "title", "price_import_usd", "costo_total_pen",
        "price_local_pen", "ahorro_pen", "roi_pct", "regimen",
        "source_import", "url_import",
    ]]

if __name__ == "__main__":
    # Test con valores de ejemplo
    print("\n" + "="*60)
    print("TEST ROI CALCULATOR")
    print("="*60)

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
        print(f"   Ahorro: S/ {r.ahorro_pen} | ROI: {r.roi_pct:.1f}%")
        print(f"   Régimen: {r.regimen} | {r.razon}")
