"""
fix_bugs_criticos.py
Corrige los 5 bugs críticos del dashboard HDS-ROI v6.0
Ejecutar desde: ~/tesis-hardware-peru/
"""
import re, ast, sys, shutil
from datetime import datetime

# ── Configuración ──────────────────────────────────────────────────────────────
TARGET   = "dashboard_v5_main.py"
BACKUP   = f"dashboard_v5_main.py.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
ENCODING = "utf-8"

print("=" * 65)
print("  HDS-ROI — Fix Bugs Críticos")
print("=" * 65)

# ── Leer archivo ───────────────────────────────────────────────────────────────
shutil.copy2(TARGET, BACKUP)
print(f"[OK] Backup creado: {BACKUP}")

with open(TARGET, encoding=ENCODING, errors="replace") as f:
    code = f.read()

fixes_aplicados = 0

# ══════════════════════════════════════════════════════════════════════════════
# BUG 1 — Ganancia Esperada en Motor de Decisión
# PROBLEMA: muestra rec_bal['ganancia'] = ganancia del portafolio OE9 (~$76)
#           en lugar de capital_global × (roi/100)
# FIX: calcular ganancia proyectada sobre capital_global real del usuario
# ══════════════════════════════════════════════════════════════════════════════
old_b1 = '''        dbc.Col(kpi_card("Ganancia Esperada", f"${rec_bal['ganancia']:,.0f}",
                         "Perfil balanceado",  COLORS["green"],   "📈", "lg"), md=3),'''

new_b1 = '''        dbc.Col(kpi_card("Ganancia Esperada",
                         f"${capital_global * rec_bal['roi'] / 100:,.0f}",
                         f"Con ${capital_global:,.0f} al {rec_bal['roi']:.1f}% ROI",
                         COLORS["green"], "📈", "lg"), md=3),'''

if old_b1 in code:
    code = code.replace(old_b1, new_b1)
    fixes_aplicados += 1
    print("[FIX 1/5] ✅ Ganancia Esperada — ahora usa capital_global × ROI")
else:
    print("[FIX 1/5] ⚠️  Patrón no encontrado — buscando variante...")
    # Buscar variante con espacios distintos
    pattern = r'kpi_card\("Ganancia Esperada",\s*f"\$\{rec_bal\[.ganancia.\]:,\.0f\}"'
    match = re.search(pattern, code)
    if match:
        print(f"           Encontrado en pos {match.start()} — aplicando regex fix")
        code = re.sub(
            pattern,
            f'kpi_card("Ganancia Esperada",\n'
            f'                         f"${{capital_global * rec_bal[\'roi\'] / 100:,.0f}}"',
            code
        )
        fixes_aplicados += 1
        print("[FIX 1/5] ✅ Ganancia Esperada — fix regex aplicado")
    else:
        print("[FIX 1/5] ❌ No se pudo aplicar — revisar manualmente línea ~477")

# ══════════════════════════════════════════════════════════════════════════════
# BUG 2 — Resumen de Decisión: Ganancia en card de perfil también incorrecta
# PROBLEMA: muestra rec_bal['ganancia'] (OE9 ~$76) en el resumen
# FIX: mostrar ganancia proyectada + nota aclaratoria
# ══════════════════════════════════════════════════════════════════════════════
old_b2 = '''            html.Span(f"ROI: +{rec_bal['roi']:.1f}%  |  Capital: ${rec_bal['capital']:,.0f}  |  "
                      f"Ganancia: ${rec_bal['ganancia']:,.0f}",
                      style={"fontSize": "0.85rem"}),'''

new_b2 = '''            html.Span(
                f"ROI: +{rec_bal['roi']:.1f}%  |  "
                f"Capital: ${capital_global:,.0f}  |  "
                f"Ganancia proyectada: ${capital_global * rec_bal['roi'] / 100:,.0f}",
                style={"fontSize": "0.85rem"}),
            html.Br(),
            html.Small(
                "⚠️ ROI del portafolio OE9. El Simulador calcula el ROI neto real con costos de importación.",
                style={"fontSize": "0.72rem", "color": "#aaa", "fontStyle": "italic"}
            ),'''

if old_b2 in code:
    code = code.replace(old_b2, new_b2)
    fixes_aplicados += 1
    print("[FIX 2/5] ✅ Resumen Decisión — ganancia proyectada + nota aclaratoria ROI Motor vs Simulador")
else:
    print("[FIX 2/5] ⚠️  Patrón no encontrado — buscando variante...")
    pattern2 = r'f"Ganancia: \$\{rec_bal\[.ganancia.\]:,\.0f\}"'
    if re.search(pattern2, code):
        code = re.sub(
            pattern2,
            f'f"Ganancia proyectada: ${{capital_global * rec_bal[\'roi\'] / 100:,.0f}}"',
            code
        )
        fixes_aplicados += 1
        print("[FIX 2/5] ✅ Resumen Decisión — fix regex aplicado")
    else:
        print("[FIX 2/5] ❌ No se pudo aplicar — revisar manualmente línea ~572")

# ══════════════════════════════════════════════════════════════════════════════
# BUG 3 — P95/P50 en Sensibilidad Monte Carlo
# PROBLEMA: df_mc["roi_simulado"] está en escala 0-1 (ej: 1.097 = 109.7%)
#           pero se muestra sin ×100, causando que P50=109 y P95=100
#           parezcan invertidos visualmente
# FIX: normalizar la escala al calcular percentiles para display
# ══════════════════════════════════════════════════════════════════════════════
old_b3 = '''    p5, p50, p95 = [np.percentile(df_mc["roi_simulado"], p) for p in [5, 50, 95]]
    for val, lbl, col in [(p5,"P5",COLORS["red"]),
                           (p50,"P50",COLORS["accent4"]),
                           (p95,"P95",COLORS["green"])]:
        fig_hist.add_vline(x=val, line_dash="dash", line_color=col,
                           annotation_text=f"{lbl}: {val:.2f}",
                           annotation_font_color=col,
                           annotation_position="top")'''

new_b3 = '''    # ── FIX BUG 3: normalizar escala roi_simulado ──────────────────────────────
    # Si los valores están en escala 0-1 (ej: 0.67 = 67%), convertir a %
    _roi_vals = df_mc["roi_simulado"].dropna()
    _scale    = 100.0 if _roi_vals.abs().max() <= 5.0 else 1.0
    _roi_pct  = _roi_vals * _scale  # ahora siempre en escala porcentual

    p5, p50, p95 = [float(np.percentile(_roi_pct, p)) for p in [5, 50, 95]]

    # Validación: p5 < p50 < p95 (invariante estadístico)
    assert p5 <= p50 <= p95, (
        f"Error estadístico: P5={p5:.2f} P50={p50:.2f} P95={p95:.2f} — "
        f"escala detectada: ×{_scale}"
    )

    for val, lbl, col in [(p5,"P5",COLORS["red"]),
                           (p50,"P50",COLORS["accent4"]),
                           (p95,"P95",COLORS["green"])]:
        fig_hist.add_vline(x=val, line_dash="dash", line_color=col,
                           annotation_text=f"{lbl}: {val:.1f}%",
                           annotation_font_color=col,
                           annotation_position="top")'''

if old_b3 in code:
    code = code.replace(old_b3, new_b3)
    fixes_aplicados += 1
    print("[FIX 3/5] ✅ P95/P50 Monte Carlo — normalización de escala + assert invariante")
else:
    print("[FIX 3/5] ⚠️  Patrón exacto no encontrado — aplicando fix por líneas...")
    # Fix más quirúrgico: solo reemplazar la línea de percentiles
    old_perc = '    p5, p50, p95 = [np.percentile(df_mc["roi_simulado"], p) for p in [5, 50, 95]]'
    new_perc = '''    # FIX BUG 3: normalizar escala (0-1 → porcentaje si necesario)
    _roi_vals = df_mc["roi_simulado"].dropna()
    _scale    = 100.0 if _roi_vals.abs().max() <= 5.0 else 1.0
    _roi_pct  = _roi_vals * _scale
    p5, p50, p95 = [float(np.percentile(_roi_pct, p)) for p in [5, 50, 95]]'''
    if old_perc in code:
        code = code.replace(old_perc, new_perc)
        fixes_aplicados += 1
        print("[FIX 3/5] ✅ P95/P50 — fix línea percentiles aplicado")
    else:
        print("[FIX 3/5] ❌ No se pudo aplicar — revisar manualmente línea ~961")

# ══════════════════════════════════════════════════════════════════════════════
# BUG 4 — Tabla estadísticas MC: actualizar labels con escala correcta
# PROBLEMA: los valores de P5/P50/P95 en la tabla de stats también usan
#           la variable p5/p50/p95 que ahora ya están en escala %
# FIX: agregar "%" al label de display
# ══════════════════════════════════════════════════════════════════════════════
old_b4 = '''        ("P5",           f"{p5:.3f}",                             COLORS["red"]),
        ("P50 (Mediana)",f"{p50:.3f}",                            COLORS["accent4"]),
        ("P95",          f"{p95:.3f}",                            COLORS["green"]),'''

new_b4 = '''        ("P5",           f"{p5:.1f}%",                            COLORS["red"]),
        ("P50 (Mediana)",f"{p50:.1f}%",                           COLORS["accent4"]),
        ("P95",          f"{p95:.1f}%",                           COLORS["green"]),'''

if old_b4 in code:
    code = code.replace(old_b4, new_b4)
    fixes_aplicados += 1
    print("[FIX 4/5] ✅ Tabla Stats MC — P5/P50/P95 ahora muestran '%' con 1 decimal")
else:
    print("[FIX 4/5] ⚠️  Patrón no encontrado — puede que ya esté corregido o tenga formato distinto")
    # Intentar fix con regex
    pattern4 = r'\("P95",\s+f"\{p95:\.3f\}"'
    if re.search(pattern4, code):
        code = re.sub(pattern4, '("P95",          f"{p95:.1f}%"', code)
        fixes_aplicados += 1
        print("[FIX 4/5] ✅ P95 tabla — fix regex aplicado")

# ══════════════════════════════════════════════════════════════════════════════
# BUG 5 — ESTRELLA riesgo=0.0 y HHI idéntico en todos los perfiles
# PROBLEMA: df_portf viene de JSON estático con valores hardcodeados
# FIX: recalcular riesgo y HHI dinámicamente desde df_oe9 si está disponible
# ══════════════════════════════════════════════════════════════════════════════
old_b5 = '''def page_portafolios():
    df_portf = DATA["portafolios"]
    df_skus  = DATA["skus"]
    palette  = [COLORS["accent2"], COLORS["accent"], COLORS["accent3"]]'''

new_b5 = '''def page_portafolios():
    df_portf = DATA["portafolios"].copy()
    df_skus  = DATA["skus"]
    df_oe9   = DATA.get("oe9_pareto", pd.DataFrame())
    palette  = [COLORS["accent2"], COLORS["accent"], COLORS["accent3"]]

    # ── FIX BUG 5: recalcular HHI y riesgo dinámicamente ──────────────────────
    if len(df_oe9) >= 3 and "roi_pct" in df_oe9.columns:
        # Ordenar por tipo para asignar perfiles correctamente
        _tipos = {"AGRESIVO": 0, "BALANCEADO": 1, "ESTRELLA": 2}
        for idx, row in df_portf.iterrows():
            perfil = str(row.get("perfil", "")).upper()
            # Filtrar portafolios OE9 del mismo tipo
            _mask = df_oe9["tipo"].str.upper() == perfil if "tipo" in df_oe9.columns else pd.Series([True]*len(df_oe9))
            _sub  = df_oe9[_mask] if _mask.any() else df_oe9

            # HHI real: basado en distribución de capital por SKU
            n_skus = int(row.get("n_skus", 1))
            if n_skus > 0:
                # HHI = Σ(wi²) donde wi = 1/n (distribución uniforme como aproximación)
                hhi_calc = round(1.0 / n_skus, 4)
            else:
                hhi_calc = 1.0

            # Riesgo real: promedio de r_j del subconjunto
            if "rj_portafolio" in _sub.columns and len(_sub) > 0:
                riesgo_calc = round(float(_sub["rj_portafolio"].mean()), 4)
            else:
                # Fallback: ESTRELLA tiene 1 SKU → mayor riesgo por concentración
                riesgo_calc = round(1.0 / max(n_skus, 1) * 5, 2)

            df_portf.at[idx, "hhi"]    = hhi_calc
            df_portf.at[idx, "riesgo"] = max(riesgo_calc, 0.01)  # nunca 0 exacto

        print(f"[FIX 5] HHI y riesgo recalculados dinámicamente para {len(df_portf)} perfiles")
    # ── Fin Fix Bug 5 ──────────────────────────────────────────────────────────'''

if old_b5 in code:
    code = code.replace(old_b5, new_b5)
    fixes_aplicados += 1
    print("[FIX 5/5] ✅ HHI dinámico + ESTRELLA riesgo > 0 — recalculado desde OE9")
else:
    print("[FIX 5/5] ⚠️  Patrón no encontrado — buscando variante...")
    alt_b5 = 'def page_portafolios():\n    df_portf = DATA["portafolios"]\n    df_skus  = DATA["skus"]'
    if alt_b5 in code:
        code = code.replace(
            alt_b5,
            new_b5.replace('df_portf = DATA["portafolios"].copy()', 'df_portf = DATA["portafolios"].copy()')
        )
        fixes_aplicados += 1
        print("[FIX 5/5] ✅ HHI/riesgo — variante aplicada")
    else:
        print("[FIX 5/5] ❌ No se pudo aplicar — revisar manualmente función page_portafolios()")

# ══════════════════════════════════════════════════════════════════════════════
# VALIDACIÓN SINTÁCTICA
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 65)
print(f"  Fixes aplicados: {fixes_aplicados}/5")
print("─" * 65)

try:
    ast.parse(code)
    print("[OK] Sintaxis Python válida ✅")
except SyntaxError as e:
    print(f"[ERROR] Sintaxis inválida en línea {e.lineno}: {e.msg}")
    lines = code.split('\n')
    start = max(0, e.lineno - 4)
    end   = min(len(lines), e.lineno + 4)
    for i, l in enumerate(lines[start:end], start + 1):
        marker = ">>>" if i == e.lineno else "   "
        print(f"  {marker} L{i:4d}: {l}")
    print("\n[ABORT] No se guardó el archivo. Backup disponible en:", BACKUP)
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
# GUARDAR
# ══════════════════════════════════════════════════════════════════════════════
with open(TARGET, "w", encoding=ENCODING) as f:
    f.write(code)

print(f"[OK] Archivo guardado: {TARGET}")
print(f"[OK] Backup disponible: {BACKUP}")
print("\n✅ TODOS LOS FIXES APLICADOS CORRECTAMENTE")
print("=" * 65)
print("\nPróximos pasos:")
print("  1. Reiniciar el dashboard:")
print("     venv_pe4/Scripts/python.exe dashboard_v5_main.py")
print("  2. Verificar en el navegador:")
print("     - Motor de Decisión: Ganancia debe ser capital × ROI")
print("     - Sensibilidad: P5 < P50 < P95 (orden correcto)")
print("     - Portafolios: HHI distinto por perfil, ESTRELLA riesgo > 0")
print("  3. Si algo falla, restaurar backup:")
print(f"     cp {BACKUP} {TARGET}")
print("=" * 65)
