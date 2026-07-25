import pathlib as _pl

p = _pl.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")

# ── FIX-12: precio local por rango de precio del importado ───────────────
OLD = '''        precio_mediano = float(local_cat["price_pen"].median())
        peso_kg        = CATEGORY_WEIGHTS.get(category, 0.5)'''

NEW = '''        precio_mediano = float(local_cat["price_pen"].median())
        peso_kg        = CATEGORY_WEIGHTS.get(category, 0.5)

        # [FIX-12] Tabla de precios locales por percentil para matching dinámico
        local_prices_sorted = local_cat["price_pen"].dropna().sort_values().values
        _local_p10 = float(local_cat["price_pen"].quantile(0.10))
        _local_p90 = float(local_cat["price_pen"].quantile(0.90))'''

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    print("OK  FIX-12a: tabla percentiles añadida")
else:
    print("!!  FIX-12a: patron no encontrado")

# ── FIX-12b: dentro del loop, precio local proporcional al precio import ──
OLD2 = '''                # [S1] ROI
                roi = calculate_roi(
                    price_import_usd=price_usd,
                    price_local_pen=precio_mediano,'''

NEW2 = '''                # [S1] ROI — [FIX-12] precio local proporcional al rango import
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
                    _precio_local = precio_mediano

                roi = calculate_roi(
                    price_import_usd=price_usd,
                    price_local_pen=_precio_local,'''

if OLD2 in src:
    src = src.replace(OLD2, NEW2, 1)
    print("OK  FIX-12b: precio local dinamico en loop")
else:
    print("!!  FIX-12b: patron no encontrado")

# ── FIX-12c: guardar _precio_local en el record ───────────────────────────
OLD3 = "                    price_local_pen=precio_mediano,"
if OLD3 in src:
    count = src.count(OLD3)
    src   = src.replace(OLD3, "                    price_local_pen=_precio_local,")
    print(f"OK  FIX-12c: price_local_pen={count} ocurrencias reemplazadas")
else:
    print("!!  FIX-12c: patron no encontrado")

p.write_text(src, encoding="utf-8")
print(f"\nArchivo guardado: {p}")
