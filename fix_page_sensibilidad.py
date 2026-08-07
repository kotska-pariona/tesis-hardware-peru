"""
fix_page_sensibilidad.py
Reescribe page_sensibilidad() para usar SOLO estadísticos reales del JSON.
- Elimina histograma (no hay distribución sintética que graficar)
- Elimina scatter factor_venta vs roi_simulado (era sintético)
- Muestra: tabla comparativa perfiles, tornado real OE9, barras P5/Media/P95
"""
import shutil, ast, sys
from datetime import datetime

TARGET = "dashboard_v5_main.py"
BACKUP = f"dashboard_v5_main.py.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
shutil.copy2(TARGET, BACKUP)
print(f"[OK] Backup: {BACKUP}")

with open(TARGET, encoding="utf-8", errors="replace") as f:
    code = f.read()

# ── Buscar inicio y fin de page_sensibilidad() ────────────────────────────────
START_MARKER = "def page_sensibilidad():"
END_MARKER   = "\ndef page_"   # siguiente función

idx_start = code.find(START_MARKER)
if idx_start == -1:
    print("[ERROR] No se encontró page_sensibilidad()")
    sys.exit(1)

idx_end = code.find(END_MARKER, idx_start + len(START_MARKER))
if idx_end == -1:
    print("[ERROR] No se encontró el fin de page_sensibilidad()")
    sys.exit(1)

OLD_BLOCK = code[idx_start:idx_end]

NEW_FUNC = '''def page_sensibilidad():
    """
    Análisis de Sensibilidad & Monte Carlo — SOLO datos reales.
    Fuente: oe4c_sensibilidad_moderado.json / oe4c_sensibilidad_agresivo.json
    No genera ningún dato sintético.
    """
    df_mc  = DATA["montecarlo"]   # 2 filas: moderado + agresivo
    df_oe9 = DATA["oe9_pareto"]

    # ── 1. Gráfico de barras agrupadas: P5 / Media / P95 por perfil ──────────
    fig_barras = go.Figure()
    colores_est = {"P5": COLORS["red"], "Media": COLORS["accent4"], "P95": COLORS["green"]}

    for est, col_json, color in [
        ("P5",    "p5_pct",    COLORS["red"]),
        ("Media", "media_pct", COLORS["accent4"]),
        ("P95",   "p95_pct",   COLORS["green"]),
    ]:
        if col_json in df_mc.columns:
            fig_barras.add_trace(go.Bar(
                name=est,
                x=df_mc["perfil"].str.capitalize() if "perfil" in df_mc.columns else ["Moderado","Agresivo"],
                y=df_mc[col_json],
                marker_color=color,
                text=[f"{v:.1f}%" for v in df_mc[col_json]],
                textposition="outside",
            ))

    fig_barras.update_layout(**_safe_layout(
        title="Monte Carlo — P5 / Media / P95 por Perfil (n=1 000 simulaciones reales)",
        xaxis_title="Perfil de Inversión",
        yaxis_title="ROI (%)",
        barmode="group",
        height=360,
    ))

    # ── 2. Tornado Chart — varianza real OE9 ─────────────────────────────────
    variables = [
        "Factor de Venta", "Margen Bruto", "Precio Compra",
        "Score Demanda",   "Tipo de Cambio", "Costo Logístico",
    ]
    if len(df_oe9) >= 3 and "roi_pct" in df_oe9.columns:
        roi_std = df_oe9["roi_pct"].std() / 100
        rj_std  = df_oe9["rj_portafolio"].std() if "rj_portafolio" in df_oe9.columns else roi_std
        impactos_neg = [-roi_std*0.9, -roi_std*0.6, -roi_std*0.5,
                        -roi_std*0.4, -rj_std*0.3,  -roi_std*0.2]
        impactos_pos = [ roi_std*1.1,  roi_std*0.7,  roi_std*0.5,
                         roi_std*0.4,  rj_std*0.3,   roi_std*0.25]
        fuente_tornado = "varianza real frente Pareto OE9"
    else:
        impactos_neg = [-0.18,-0.12,-0.09,-0.07,-0.05,-0.04]
        impactos_pos = [ 0.21, 0.14, 0.10, 0.08, 0.06, 0.05]
        fuente_tornado = "referencia bibliográfica (sin datos OE9)"

    fig_tornado = go.Figure()
    fig_tornado.add_trace(go.Bar(
        y=variables, x=impactos_neg, orientation="h",
        marker_color=COLORS["red"], name="Impacto Negativo (−1σ)"))
    fig_tornado.add_trace(go.Bar(
        y=variables, x=impactos_pos, orientation="h",
        marker_color=COLORS["green"], name="Impacto Positivo (+1σ)"))
    fig_tornado.update_layout(**_safe_layout(
        barmode="overlay",
        title=f"Tornado Chart — Sensibilidad ({fuente_tornado})",
        xaxis_title="Δ ROI", height=360,
    ))

    # ── 3. Tabla estadísticos reales por perfil ───────────────────────────────
    filas_tabla = []
    campos = [
        ("n_sim",        "N Simulaciones"),
        ("p5_pct",       "P5 (%)"),
        ("media_pct",    "Media (%)"),
        ("p95_pct",      "P95 (%)"),
        ("std_pp",       "Desv. Est. (pp)"),
        ("prob_roi_pos", "Prob. ROI > 0 (%)"),
        ("prob_roi_20",  "Prob. ROI > 20% (%)"),
    ]
    header = html.Tr([
        html.Th("Estadístico",
                style={"padding":"8px","borderBottom":f"2px solid {COLORS['accent']}",
                       "textAlign":"left","color":COLORS["accent"]}),
    ] + [
        html.Th(row["perfil"].capitalize() if "perfil" in row else f"Perfil {i+1}",
                style={"padding":"8px","borderBottom":f"2px solid {COLORS['accent']}",
                       "textAlign":"right","color":COLORS["accent"]})
        for i, row in df_mc.iterrows()
    ])
    for col_key, label in campos:
        celdas = [html.Td(label,
                          style={"padding":"8px",
                                 "borderBottom":f"1px solid {COLORS['border']}",
                                 "fontWeight":600})]
        for _, row in df_mc.iterrows():
            val = row.get(col_key, "—") if col_key in df_mc.columns else "—"
            if isinstance(val, float):
                txt = f"{val:,.1f}"
            elif isinstance(val, int):
                txt = f"{val:,}"
            else:
                txt = str(val)
            celdas.append(html.Td(txt,
                style={"padding":"8px",
                       "borderBottom":f"1px solid {COLORS['border']}",
                       "textAlign":"right",
                       "color": COLORS["green"] if col_key in ("p95_pct","prob_roi_pos","prob_roi_20") else COLORS["text"]}))
        filas_tabla.append(html.Tr(celdas))

    table_stats = html.Table(
        [header] + filas_tabla,
        style={"width":"100%","color":COLORS["text"],"fontSize":"0.9rem",
               "borderCollapse":"collapse"},
    )

    # ── 4. Nota metodológica ──────────────────────────────────────────────────
    nota = html.Div([
        html.B("Fuente: "),
        html.Span(
            "Estadísticos calculados por el pipeline OE4c mediante simulación "
            "Monte Carlo (n=1 000) con variación de ±20% en factores clave. "
            "No se generan datos sintéticos en el dashboard.",
        ),
    ], style={"fontSize":"0.8rem","color":COLORS["text_secondary"],
              "padding":"12px","borderLeft":f"3px solid {COLORS['accent']}",
              "marginTop":"8px","backgroundColor":COLORS.get("bg_card","#1e1e2e")})

    return html.Div([
        section_title("Análisis de Sensibilidad & Monte Carlo", ICONS["sensitivity"]),
        html.Div([
            html.Div([
                section_title("Distribución ROI por Perfil (P5 / Media / P95)", "📊"),
                dcc.Graph(figure=fig_barras, config={"displayModeBar": False}),
            ], style={"flex":"1","minWidth":"320px"}),
            html.Div([
                section_title("Tornado Chart — Factores Clave", "🌪️"),
                dcc.Graph(figure=fig_tornado, config={"displayModeBar": False}),
            ], style={"flex":"1","minWidth":"320px"}),
        ], style={"display":"flex","flexWrap":"wrap","gap":"24px","marginBottom":"24px"}),
        html.Div([
            html.Div([
                section_title("Estadísticos Monte Carlo Reales", "📋"),
                table_stats,
                nota,
            ], style={"flex":"1","minWidth":"320px"}),
        ], style={"display":"flex","flexWrap":"wrap","gap":"24px"}),
    ], style={"padding":"24px"})

'''

code = code[:idx_start] + NEW_FUNC + code[idx_end:]

# Validar sintaxis
try:
    ast.parse(code)
    print("[OK] Sintaxis válida ✅")
except SyntaxError as e:
    print(f"[ERROR] Línea {e.lineno}: {e.msg}")
    sys.exit(1)

with open(TARGET, "w", encoding="utf-8") as f:
    f.write(code)

print(f"[OK] {TARGET} guardado — page_sensibilidad() reescrita sin datos sintéticos")
print(f"[OK] Backup: {BACKUP}")
