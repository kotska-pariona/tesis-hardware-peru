"""
FIX-19: Price-Band Matching
Reemplaza la mediana global de categoría por el precio mediano
del segmento local equivalente al precio del producto importado.

Lógica:
  1. Convertir price_import_usd → PEN
  2. Buscar productos locales en rango [import_pen * 0.5, import_pen * 2.0]
  3. Si hay >= 3 productos → usar su mediana como precio_local
  4. Si hay < 3 → expandir rango a [import_pen * 0.3, import_pen * 3.0]
  5. Si aún < 3 → usar mediana del cuartil más cercano (Q1/Q2/Q3/Q4)
  6. Filtro de calidad: descartar productos import con título < 4 palabras
     (elimina "ARCTIC", "Intel", "Intel Core" sin modelo)
"""

import pathlib, re

TARGET = pathlib.Path("agent/pe5_agent.py")
src = TARGET.read_text(encoding="utf-8")
lines = src.splitlines()

# ── 1. Insertar helper _get_price_band_ref ANTES de _analyze_category ──────
HELPER = '''
    # [FIX-19] Price-Band Matching helper
    @staticmethod
    def _get_price_band_ref(
        local_prices: "pd.Series",
        import_usd: float,
        usd_pen: float,
        precio_mediano: float,
    ) -> float:
        """
        Devuelve el precio local de referencia para un producto importado
        usando price-band matching en lugar de la mediana global.
        """
        import numpy as np
        import_pen = import_usd * usd_pen

        # Banda primaria: ±100% del precio importado en PEN
        band_lo = import_pen * 0.50
        band_hi = import_pen * 2.00
        band = local_prices[(local_prices >= band_lo) & (local_prices <= band_hi)]

        if len(band) >= 3:
            return float(band.median())

        # Banda secundaria: ±200%
        band_lo2 = import_pen * 0.30
        band_hi2 = import_pen * 3.00
        band2 = local_prices[(local_prices >= band_lo2) & (local_prices <= band_hi2)]
        if len(band2) >= 3:
            return float(band2.median())

        # Fallback: mediana del cuartil más cercano
        q25 = float(local_prices.quantile(0.25))
        q50 = float(local_prices.quantile(0.50))
        q75 = float(local_prices.quantile(0.75))
        q_max = float(local_prices.max())

        if import_pen <= q25:
            seg = local_prices[local_prices <= q25]
        elif import_pen <= q50:
            seg = local_prices[(local_prices > q25) & (local_prices <= q50)]
        elif import_pen <= q75:
            seg = local_prices[(local_prices > q50) & (local_prices <= q75)]
        else:
            seg = local_prices[local_prices > q75]

        if len(seg) >= 1:
            return float(seg.median())

        return precio_mediano  # último recurso

'''

# ── 2. Filtro de calidad de título (mínimo 4 palabras con contenido) ────────
TITLE_FILTER = '''
                # [FIX-19] Filtro calidad de título: descartar si < 4 tokens reales
                _title_tokens = [t for t in title.lower().split()
                                 if len(t) > 1 and not t.isdigit()]
                if len(_title_tokens) < 4:
                    continue

'''

# ── 3. Reemplazar L755: _precio_local = precio_mediano ──────────────────────
OLD_PRECIO_LOCAL = "                _precio_local = precio_mediano"
NEW_PRECIO_LOCAL = (
    "                # [FIX-19] Price-band matching: precio local del segmento equivalente\n"
    "                _local_prices_series = local_cat[\"price_pen\"]\n"
    "                _precio_local = self._get_price_band_ref(\n"
    "                    local_prices=_local_prices_series,\n"
    "                    import_usd=price_usd,\n"
    "                    usd_pen=usd_pen,\n"
    "                    precio_mediano=precio_mediano,\n"
    "                )"
)

# ── Aplicar cambios ──────────────────────────────────────────────────────────
new_src = src

# 3a. Reemplazar _precio_local
if OLD_PRECIO_LOCAL in new_src:
    new_src = new_src.replace(OLD_PRECIO_LOCAL, NEW_PRECIO_LOCAL, 1)
    print("✅ [3] _precio_local → price-band matching")
else:
    print("❌ [3] No se encontró OLD_PRECIO_LOCAL — revisar indentación")

# 3b. Insertar filtro de título ANTES del bloque ROI (después de "if price_usd <= 0")
OLD_ROI_BLOCK = (
    "                if price_usd <= 0 or not title:\n"
    "                    continue\n"
    "\n"
    "                # [S1] ROI"
)
NEW_ROI_BLOCK = (
    "                if price_usd <= 0 or not title:\n"
    "                    continue\n"
    "\n"
    + TITLE_FILTER +
    "                # [S1] ROI"
)
if OLD_ROI_BLOCK in new_src:
    new_src = new_src.replace(OLD_ROI_BLOCK, NEW_ROI_BLOCK, 1)
    print("✅ [2] Filtro de calidad de título insertado")
else:
    print("❌ [2] No se encontró bloque ROI para insertar filtro título")

# 3c. Insertar helper _get_price_band_ref
# Buscar "def _analyze_category" y pegar el helper ANTES
ANCHOR = "    def _analyze_category("
if ANCHOR in new_src:
    new_src = new_src.replace(ANCHOR, HELPER + ANCHOR, 1)
    print("✅ [1] Helper _get_price_band_ref insertado")
else:
    print("❌ [1] No se encontró def _analyze_category")

# ── Guardar ──────────────────────────────────────────────────────────────────
TARGET.write_text(new_src, encoding="utf-8")
print()
print("✅ FIX-19 aplicado → agent/pe5_agent.py")
print("   Próximo paso: borrar pe5_decisions.csv y re-ejecutar pipeline")
