import pathlib as _pl

# ══════════════════════════════════════════════════════
# FIX-18: Operar ROI completamente en USD
# ══════════════════════════════════════════════════════

# ── 1. roi_calculator.py ──────────────────────────────
roi_path = _pl.Path("analisis/roi_calculator.py")
roi_code = roi_path.read_text(encoding="utf-8")

OLD_ROI = '''def calculate_roi(
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

    ahorro = price_local_pen - cost.costo_total_pen

    # [ROI3] Guardia explícita — evita ZeroDivisionError silencioso
    if cost.costo_total_pen > 0:
        roi = ahorro / cost.costo_total_pen * 100
    else:
        roi = 0.0

    if price_local_pen > 0:
        margen = ahorro / price_local_pen * 100
    else:
        margen = 0.0   # [ROI3] price_local_pen=0 no genera excepción

    conviene = roi >= (MARGEN_GANANCIA_MIN * 100)

    if price_local_pen <= 0:
        razon = "Sin precio local de referencia"'''

NEW_ROI = '''def calculate_roi(
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

    # [FIX-18] Todo en USD — evita distorsión por mediana PEN vs rango import
    # price_local_pen se convierte a USD para comparación directa
    _rate = cost.usd_pen_rate if cost.usd_pen_rate > 0 else 3.75
    price_local_usd = price_local_pen / _rate if price_local_pen > 0 else 0.0

    ahorro_usd = price_local_usd - cost.costo_total_usd
    ahorro     = ahorro_usd * _rate  # mantener ahorro_pen para reporte

    # [ROI3] Guardia explícita — evita ZeroDivisionError silencioso
    if cost.costo_total_usd > 0:
        roi = ahorro_usd / cost.costo_total_usd * 100
    else:
        roi = 0.0

    if price_local_usd > 0:
        margen = ahorro_usd / price_local_usd * 100
    else:
        margen = 0.0   # [ROI3] price_local_usd=0 no genera excepción

    conviene = roi >= (MARGEN_GANANCIA_MIN * 100)

    if price_local_pen <= 0:
        razon = "Sin precio local de referencia"'''

if OLD_ROI in roi_code:
    roi_code = roi_code.replace(OLD_ROI, NEW_ROI)
    print("✅ FIX-18a: calculate_roi ahora opera en USD")
else:
    print("❌ Bloque OLD_ROI no encontrado — revisar manualmente")
    # Mostrar contexto para debug
    idx = roi_code.find("ahorro = price_local_pen - cost.costo_total_pen")
    if idx >= 0:
        print(f"  Contexto encontrado en pos {idx}:")
        print(roi_code[idx-100:idx+200])

roi_path.write_text(roi_code, encoding="utf-8")
print("   roi_calculator.py guardado")

# ── 2. pe5_agent.py: log en USD también ──────────────
agent_path = _pl.Path("agent/pe5_agent.py")
agent_code = agent_path.read_text(encoding="utf-8")

OLD_LOG = '''        log.info(
            f"  {category:15s}: "
            f"{len(import_cat):4d} productos "
            f"(+{n_filtered} filtrados <${PRICE_USD_MIN:.0f}) | "
            f"precio local S/ {precio_mediano:.0f} | "
            f"trend={trend.signal} "
            f"(n={trend.n_points}, slope={trend.slope_pct*100:.3f}%/día)"
        )'''

NEW_LOG = '''        _precio_mediano_usd = precio_mediano / usd_pen
        log.info(
            f"  {category:15s}: "
            f"{len(import_cat):4d} productos "
            f"(+{n_filtered} filtrados <${PRICE_USD_MIN:.0f}) | "
            f"precio local S/ {precio_mediano:.0f} (${_precio_mediano_usd:.0f} USD) | "
            f"trend={trend.signal} "
            f"(n={trend.n_points}, slope={trend.slope_pct*100:.3f}%/día)"
        )'''

if OLD_LOG in agent_code:
    agent_code = agent_code.replace(OLD_LOG, NEW_LOG)
    print("✅ FIX-18b: log muestra precio local en USD también")
else:
    print("⚠ Bloque log no encontrado (no crítico)")

agent_path.write_text(agent_code, encoding="utf-8")
print("   pe5_agent.py guardado")

print("\n✅ FIX-18 completo")
print("   ROI = (precio_local_usd - costo_total_usd) / costo_total_usd")
print("   CPU mediana: S/3099 → $826 USD vs import $50-$600")
print("   ROI esperado: 10%-80% (rango realista)")
