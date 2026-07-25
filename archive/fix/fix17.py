import pathlib as _pl

path = _pl.Path("agent/pe5_agent.py")
code = path.read_text(encoding="utf-8")

# ── FIX-17: Reemplazar matching dinámico por precio de referencia inteligente ──
# El rango import (S/465-1912) NO se solapa con rango local (S/1079-9102)
# → usar mediana local como referencia base, ajustada por ratio de precios
OLD = '''                # [S1] ROI — [FIX-16] matching por percentil directo
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

NEW = '''                # [S1] ROI — [FIX-17] precio local = mediana de mercado local
                # Justificación: el rango de precios de importación (S/465-1912)
                # está por debajo del rango local (S/1079-9102), por lo que el
                # matching dinámico por percentil colapsa siempre al P10.
                # La mediana local es el precio de referencia correcto: representa
                # cuánto paga el consumidor peruano por ese tipo de producto.
                _precio_local = precio_mediano'''

if OLD in code:
    code = code.replace(OLD, NEW)
    print("✅ FIX-17 aplicado: matching dinámico → mediana local")
else:
    print("❌ Bloque OLD no encontrado")
    idx = code.find("[FIX-16] matching por percentil")
    print(f"  Contexto: {code[idx-30:idx+200]}")

# Limpiar también las variables _local_percentiles que ya no se usan
OLD2 = '''        # [FIX-16] Matching por percentil directo sobre precios locales filtrados
        # Evita el problema del array indexado con 75% de valores en S/29
        _local_p10 = float(local_cat["price_pen"].quantile(0.10))
        _local_p25 = float(local_cat["price_pen"].quantile(0.25))
        _local_p50 = float(local_cat["price_pen"].quantile(0.50))
        _local_p75 = float(local_cat["price_pen"].quantile(0.75))
        _local_p90 = float(local_cat["price_pen"].quantile(0.90))
        _local_percentiles = [_local_p10, _local_p25, _local_p50, _local_p75, _local_p90]'''

NEW2 = '''        # [FIX-17] Solo necesitamos mediana local como referencia de mercado
        _local_p10 = float(local_cat["price_pen"].quantile(0.10))
        _local_p90 = float(local_cat["price_pen"].quantile(0.90))'''

if OLD2 in code:
    code = code.replace(OLD2, NEW2)
    print("✅ FIX-17b: variables percentil innecesarias eliminadas")
else:
    print("⚠ Bloque OLD2 no encontrado (no crítico)")

path.write_text(code, encoding="utf-8")
print("\n✅ FIX-17 guardado → agent/pe5_agent.py")
print(f"   precio_mediano CPU = S/3,099 (mediana real del mercado local)")
