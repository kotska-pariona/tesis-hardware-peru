import pathlib as _pl
import re

path = _pl.Path("agent/pe5_agent.py")
code = path.read_text(encoding="utf-8")

# ── FIX-16: Filtro precio mínimo local + matching por percentil directo ──
OLD = '''        # Precio local de referencia
        local_cat["price_pen"] = pd.to_numeric(
            local_cat["price_pen"], errors="coerce"
        )
        local_cat = local_cat[local_cat["price_pen"] > 0]
        if local_cat.empty:
            return

        precio_mediano = float(local_cat["price_pen"].median())
        peso_kg        = CATEGORY_WEIGHTS.get(category, 0.5)

        # [FIX-12] Tabla de precios locales por percentil para matching dinámico
        local_prices_sorted = local_cat["price_pen"].dropna().sort_values().values
        _local_p10 = float(local_cat["price_pen"].quantile(0.10))
        _local_p90 = float(local_cat["price_pen"].quantile(0.90))'''

NEW = '''        # Precio local de referencia
        local_cat["price_pen"] = pd.to_numeric(
            local_cat["price_pen"], errors="coerce"
        )
        local_cat = local_cat[local_cat["price_pen"] > 0]
        if local_cat.empty:
            return

        # [FIX-16] Filtro precio mínimo local por categoría
        # Elimina accesorios/ruido (S/29) que contaminan el matching
        LOCAL_PRICE_MIN_PEN = {
            "CPU": 200, "GPU": 300, "RAM": 50, "SSD": 50,
            "LAPTOP": 500, "MONITOR": 150, "MOTHERBOARD": 150,
            "PSU": 80, "COOLER": 30, "CASE": 80,
            "KEYBOARD": 30, "MOUSE": 20, "HEADSET": 30,
        }
        _local_min = LOCAL_PRICE_MIN_PEN.get(category, 30)
        local_cat = local_cat[local_cat["price_pen"] >= _local_min]
        if local_cat.empty:
            return

        precio_mediano = float(local_cat["price_pen"].median())
        peso_kg        = CATEGORY_WEIGHTS.get(category, 0.5)

        # [FIX-16] Matching por percentil directo sobre precios locales filtrados
        # Evita el problema del array indexado con 75% de valores en S/29
        _local_p10 = float(local_cat["price_pen"].quantile(0.10))
        _local_p25 = float(local_cat["price_pen"].quantile(0.25))
        _local_p50 = float(local_cat["price_pen"].quantile(0.50))
        _local_p75 = float(local_cat["price_pen"].quantile(0.75))
        _local_p90 = float(local_cat["price_pen"].quantile(0.90))
        _local_percentiles = [_local_p10, _local_p25, _local_p50, _local_p75, _local_p90]'''

if OLD in code:
    code = code.replace(OLD, NEW)
    print("✅ Bloque precio local reemplazado")
else:
    print("❌ Bloque OLD no encontrado — verificar manualmente")
    # Mostrar contexto para debug
    idx = code.find("precio_mediano = float(local_cat")
    print(f"  Contexto: ...{code[idx-100:idx+200]}...")

# ── FIX-16b: Reemplazar lógica de matching dinámico ──
OLD2 = '''                # [S1] ROI — [FIX-12] precio local proporcional al rango import
                # Escala el precio local según la posición relativa del import
                # dentro del rango de precios de importación de la categoría
                _import_pen = price_usd * usd_pen
                if _local_p90 > _local_p10:
                    _ratio = (_import_pen - _local_p10) / (_local_p90 - _local_p10)
                    _ratio = max(0.0, min(1.0, _ratio))
                    import numpy as _np
                    _idx   = int(_ratio * (len(local_prices_sorted) - 1))
                    _precio_local = float(local_prices_sorted[_idx])
                else:
                    _precio_local = precio_mediano'''

NEW2 = '''                # [S1] ROI — [FIX-16] matching por percentil directo
                # Mapea precio_import_pen al percentil equivalente del mercado local
                # usando 5 puntos de anclaje (P10/P25/P50/P75/P90)
                _import_pen = price_usd * usd_pen
                if _local_p90 > _local_p10:
                    _ratio = (_import_pen - _local_p10) / (_local_p90 - _local_p10)
                    _ratio = max(0.0, min(1.0, _ratio))
                    # Interpolar entre percentiles anclados
                    _anchors = [0.0, 0.25, 0.50, 0.75, 1.0]
                    _vals    = _local_percentiles
                    import numpy as _np
                    _precio_local = float(_np.interp(_ratio, _anchors, _vals))
                else:
                    _precio_local = precio_mediano'''

if OLD2 in code:
    code = code.replace(OLD2, NEW2)
    print("✅ Bloque matching dinámico reemplazado")
else:
    print("❌ Bloque OLD2 no encontrado")
    idx2 = code.find("[FIX-12] precio local proporcional")
    print(f"  Contexto: ...{code[idx2-50:idx2+300]}...")

path.write_text(code, encoding="utf-8")
print("\n✅ FIX-16 aplicado → agent/pe5_agent.py guardado")
