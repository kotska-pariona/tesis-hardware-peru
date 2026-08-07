import pathlib as _pl
import re

p = _pl.Path("agent/pe5_agent.py")
src = p.read_text(encoding="utf-8")

# ══════════════════════════════════════════════════════════════
# FIX-13: Filtro de precio máximo por categoría (excluir PCs completos)
# Un CPU individual no cuesta más de $600
# ══════════════════════════════════════════════════════════════
OLD13 = '''        # [FIX-3] Filtrar productos de bajo precio (ruido Kaggle/histórico)
        n_before = len(import_cat)
        import_cat = import_cat[import_cat["price_usd"] >= PRICE_USD_MIN]
        n_filtered = n_before - len(import_cat)'''

NEW13 = '''        # [FIX-3] Filtrar productos de bajo precio (ruido Kaggle/histórico)
        # [FIX-13] Filtrar productos de precio excesivo (PCs completos en cat CPU, etc.)
        PRICE_USD_MAX = {
            "CPU": 600, "GPU": 1500, "RAM": 400, "SSD": 500,
            "Motherboard": 800, "PSU": 400, "Cooler": 300,
            "Case": 400, "Monitor": 1200, "Keyboard": 300,
            "Mouse": 200, "Headset": 400, "Webcam": 300,
        }
        n_before = len(import_cat)
        import_cat = import_cat[import_cat["price_usd"] >= PRICE_USD_MIN]
        _max_usd = PRICE_USD_MAX.get(category, 9999)
        import_cat = import_cat[import_cat["price_usd"] <= _max_usd]
        n_filtered = n_before - len(import_cat)'''

if OLD13 in src:
    src = src.replace(OLD13, NEW13, 1)
    print("OK  FIX-13: filtro precio máximo por categoría")
else:
    print("!!  FIX-13: patron no encontrado")

# ══════════════════════════════════════════════════════════════
# FIX-14: Deduplicación — 1 registro por título único por categoría
# ══════════════════════════════════════════════════════════════
OLD14 = '''        for _, row in import_cat.iterrows():'''

NEW14 = '''        # [FIX-14] Deduplicar: 1 producto por título normalizado
        import_cat["_title_key"] = (
            import_cat["title"]
            .str.lower()
            .str.replace(r"[^a-z0-9 ]", " ", regex=True)
            .str.split().str[:6].str.join(" ")
        )
        import_cat = import_cat.drop_duplicates(subset="_title_key", keep="first")

        for _, row in import_cat.iterrows():'''

if OLD14 in src:
    src = src.replace(OLD14, NEW14, 1)
    print("OK  FIX-14: deduplicación por título")
else:
    print("!!  FIX-14: patron no encontrado")

# ══════════════════════════════════════════════════════════════
# FIX-15: Implementar WAIT cuando trend=DOWN y ROI es positivo
# Buscar el bloque de decisión
# ══════════════════════════════════════════════════════════════
OLD15 = '''                roi_signal = "BUY" if roi.conviene_importar else "NO_BUY"'''

NEW15 = '''                # [FIX-15] WAIT: ROI positivo pero tendencia bajando → esperar mejor precio
                if roi.conviene_importar and trend.signal == "DOWN":
                    roi_signal = "WAIT"
                elif roi.conviene_importar:
                    roi_signal = "BUY"
                else:
                    roi_signal = "NO_BUY"'''

if OLD15 in src:
    src = src.replace(OLD15, NEW15, 1)
    print("OK  FIX-15: lógica WAIT implementada")
else:
    print("!!  FIX-15: patron no encontrado")

p.write_text(src, encoding="utf-8")
print(f"\nArchivo guardado: {p}")
